"""YomiFont font builder: rule set -> .ttf."""
from __future__ import annotations

import os
import time
from collections import defaultdict

from fontTools import subset
from fontTools.ttLib import TTFont, newTable

from . import explicit as explicit_mod
from . import gsub as gsub_mod
from .layout import DEFAULT_POLICY, layout_word
from .rubyglyphs import (RUBY_Y, add_blank_glyph, add_protected_glyphs,
                         add_ruby_glyphs, variant_name)
from .rules import Rule

# Vertical metrics.  Ruby sits at RUBY_Y (940); the tallest ruby glyph in the
# inventory (ざ at 0.5 em, dakuten included) reaches y=1373, so the ascent has
# to clear that or engines clip it.  1400 leaves 27 units of headroom and gives
# a 1.69 em default line box, which is inside the normal range for
# ruby-bearing Japanese text and was verified not to overlap between lines.
ASCENT = 1400
DESCENT = -288

DEFAULT_BASE = "data/raw/NotoSansJP-Regular.ttf"
DEFAULT_RUBY_SOURCE = "data/raw/NotoSansJP-w500.ttf"


def _needed_chars(rules: list[Rule], policy: str = DEFAULT_POLICY,
                  ex: "explicit_mod.Limits | None" = None,
                  ex_alphabet: str = "", ex_grid: int = explicit_mod.GRID):
    """Characters needed from the base font, and (kana, size, x) ruby variants."""
    base_chars: set[str] = set()
    ruby: set[tuple[str, float, int]] = set()
    for r in rules:
        base_chars.update(r.seq)
        for p in layout_word(r.groups, policy):
            base_chars.add(p.kana)   # the ruby glyph is derived from the kana
            ruby.add((p.kana, p.size, p.x))
    if ex is not None:
        # Explicit ruby needs its whole alphabet present as ordinary glyphs
        # (they are the source outlines) and the delimiters kept through
        # subsetting, plus one variant per (kana, size, offset).
        base_chars.update(ex_alphabet)
        base_chars.update(explicit_mod.DELIMITERS)
        ruby.update(explicit_mod.inventory(ex_alphabet, ex, policy, ex_grid))
        ruby.update(explicit_mod.split_inventory(ex_alphabet, ex))
    return base_chars, ruby


def extract_vert_mapping(font: TTFont) -> dict[str, str]:
    """The base font's vertical-form substitutions (、。「」 rotate in tategaki).

    YomiFont replaces GSUB wholesale, so these have to be carried across or
    vertical text loses its punctuation forms.
    """
    out: dict[str, str] = {}
    if "GSUB" not in font or font["GSUB"].table.FeatureList is None:
        return out
    tbl = font["GSUB"].table
    for frec in tbl.FeatureList.FeatureRecord:
        if frec.FeatureTag not in ("vert", "vrt2"):
            continue
        for li in frec.Feature.LookupListIndex:
            lk = tbl.LookupList.Lookup[li]
            if lk.LookupType != 1:
                continue
            for st in lk.SubTable:
                out.update(getattr(st, "mapping", {}) or {})
    return out


# A TrueType font addresses glyphs with a uint16, so this is a hard wall, and
# with explicit ruby the build now runs close enough to it that the extra base
# characters have to be budgeted rather than simply taken.
GLYPH_CEILING = 65535
# The estimate below counts the characters asked for; the subsetter keeps about
# a thousand more (vertical forms, components of kept composites), so the margin
# has to cover that and still leave the build somewhere to grow.
GLYPH_MARGIN = 3500


def kanji_repertoire(base_path: str, budget: int | None = None,
                     have: set[str] | None = None) -> list[str]:
    """CJK ideographs the base font can draw, most useful first.

    The automatic side only needs the characters its rules mention -- 5,055
    kanji.  An explicit reading is most useful exactly where the dictionary has
    nothing (unusual names, coined words, ateji), so restricting explicit-ruby
    bases to the dictionary's own character set would remove much of the
    feature's reason to exist.  Noto Sans JP can draw 13,313.

    Taking all of them does not fit: it lands at ~65,600 glyphs against a
    65,535 ceiling.  So they are ordered by how likely they are to be wanted --
    the Unified Ideographs block, which holds every common and name kanji,
    ahead of Extension A and the compatibility ideographs -- and the caller
    passes whatever budget is left over.
    """
    cmap = TTFont(base_path, lazy=True).getBestCmap()

    def rank(c: int) -> tuple[int, int]:
        if 0x4E00 <= c <= 0x9FFF:      # Unified Ideographs: the common set
            return (0, c)
        if c == 0x3005:                # 々
            return (0, c)
        if 0x3400 <= c <= 0x4DBF:      # Extension A: rare
            return (1, c)
        return (2, c)                  # compatibility ideographs

    # `have` is what the rules already pull in. The budget buys *new* glyphs,
    # so spending it on characters that are present anyway would silently
    # leave most of the headroom unused.
    have = have or set()
    out = sorted((c for c in cmap
                  if (0x3400 <= c <= 0x4DBF or 0x4E00 <= c <= 0x9FFF
                      or 0xF900 <= c <= 0xFAFF or c == 0x3005)
                  and chr(c) not in have), key=rank)
    return [chr(c) for c in (out if budget is None else out[:max(budget, 0)])]


def make_base_font(base_path: str, chars: set[str], keep_all: bool = False) -> TTFont:
    """Subset the licensed base font down to the characters YomiFont needs."""
    font = TTFont(base_path)
    if keep_all:
        return font
    opts = subset.Options()
    opts.layout_features = ["vert", "vrt2"]  # kept only to be re-extracted
    opts.glyph_names = True
    opts.notdef_outline = True
    opts.recalc_bounds = True
    opts.drop_tables += ["BASE", "STAT", "gasp", "DSIG"]
    opts.name_IDs = ["*"]
    opts.name_legacy = True
    opts.name_languages = ["*"]
    ss = subset.Subsetter(options=opts)
    # keep ASCII and Japanese punctuation so the font is usable on its own
    extra = "".join(chr(c) for c in range(0x20, 0x7F))
    # Japanese punctuation the font should be able to draw on its own. 《》 in
    # particular: they stopped being explicit-ruby delimiters, and dropping
    # them from here as well would have left ordinary 小説《ノルウェイの森》
    # falling back to another face mid-sentence.
    extra += "。、！？「」『』（）〈〉《》【】〔〕・ー〜　0123456789"
    ss.populate(text="".join(sorted(chars)) + extra)
    ss.subset(font)
    return font


def build_font(
    rules: list[Rule],
    base_path: str = DEFAULT_BASE,
    out_path: str = "dist/YomiFont-Regular.ttf",
    family: str = "YomiFont",
    verbose: bool = True,
    keep_all_glyphs: bool = False,
    keep_glyph_names: bool = True,
    policy: str = DEFAULT_POLICY,
    ruby_source: str = DEFAULT_RUBY_SOURCE,
    explicit: "explicit_mod.Limits | None" = explicit_mod.DEFAULT_LIMITS,
    explicit_latin: bool = False,
    explicit_grid: int = explicit_mod.GRID,
    explicit_bases: bool = True,
    extra_chars: str = "",
) -> dict:
    t0 = time.time()
    ex_alphabet = explicit_mod.alphabet(explicit_latin) if explicit else ""
    base_chars, ruby_needed = _needed_chars(rules, policy, explicit,
                                            ex_alphabet, explicit_grid)
    base_chars.update(extra_chars)
    if explicit and explicit_bases:
        # Everything else is already counted: the base characters the rules
        # need, every ruby variant, and one protected duplicate per glyph that
        # can start a lexical rule. Whatever is left under the ceiling goes to
        # widening the repertoire of characters an explicit base may use.
        committed = len(base_chars) + len(ruby_needed) + len(
            {r.seq[0] for r in rules})
        budget = GLYPH_CEILING - GLYPH_MARGIN - committed
        extra = kanji_repertoire(base_path, budget, have=base_chars)
        base_chars |= set(extra)
        if verbose:
            print(f"[build] base repertoire: {committed} glyphs committed, "
                  f"{budget} spare -> +{len(extra)} kanji for explicit bases")
    font = make_base_font(base_path, base_chars, keep_all=keep_all_glyphs)
    cmap = font.getBestCmap()
    vert_map = extract_vert_mapping(font)
    t_subset = time.time()

    # ---- ruby inventory -------------------------------------------------
    new_glyphs = add_ruby_glyphs(font, ruby_needed, ruby_y=RUBY_Y,
                                source_path=ruby_source)
    blank = add_blank_glyph(font)
    t_ruby = time.time()

    # ---- rules -> glyph sequences ---------------------------------------
    dropped = 0
    ms_pairs: list[tuple[str, tuple[str, ...]]] = []
    prepared: list[tuple[str, list[str], tuple[str, ...], int]] = []
    for r in rules:
        try:
            seq = [cmap[ord(c)] for c in r.seq]
        except KeyError:
            dropped += 1
            continue
        out: list[str] = []
        ok = True
        for p in layout_word(r.groups, policy):
            vn = variant_name(p.kana, p.size, p.x)
            if vn not in font["glyf"].glyphs:
                ok = False
                break
            out.append(vn)
        if not ok:
            dropped += 1
            continue
        # A rule with no ruby is a BLOCK: it consumes the sequence and emits
        # only the base glyph, which is what stops a shorter rule from firing
        # on an ambiguous word.
        out.append(seq[0])
        prepared.append((seq[0], seq, tuple(out), len(r.seq)))
        ms_pairs.append((seq[0], tuple(out)))

    ms_lookups, ms_index = gsub_mod.build_multiple_subst_lookups(ms_pairs)
    n_ms = len(ms_lookups)

    # ---- explicit ruby ---------------------------------------------------
    # Built before the glyph order is frozen, because the base-protection
    # duplicates are new glyphs and every coverage below is keyed on glyph id.
    #
    # These lookups go at the *front* of the LookupList. All that is required
    # is that they precede the lexical chain -- lookups run in index order and
    # explicit ruby has to claim its base span before the chain gets its pass
    # -- and the front is the position that leaves the MultipleSubst block's
    # own internal offsets untouched.
    first_glyphs = sorted({seq[0] for _, seq, _, _ in prepared})
    explicit_lookups: list = []
    ex_info: dict = {}
    if explicit:
        placements = explicit_mod.placements(explicit, policy, explicit_grid)
        protect = add_protected_glyphs(font, first_glyphs)
        glyph_order = {g: i for i, g in enumerate(font.getGlyphOrder())}
        delims = {cmap[ord(c)] for c in explicit_mod.DELIMITERS if ord(c) in cmap}
        ruby_alpha = [c for c in ex_alphabet if ord(c) in cmap]
        ruby_maps = {
            cell: {cmap[ord(c)]: variant_name(c, *cell) for c in ruby_alpha
                   if variant_name(c, *cell) in font["glyf"].glyphs}
            for cell in {c for cells in placements.values() for c in cells}
        }
        explicit_lookups = gsub_mod.build_explicit_lookups(
            placements,
            hide={g: blank for g in delims},
            protect=protect,
            ruby=ruby_maps,
            coverage={
                "start": [cmap[ord(c)] for c in explicit_mod.START if ord(c) in cmap],
                "open": [cmap[ord(c)] for c in explicit_mod.OPEN if ord(c) in cmap],
                "close": [cmap[ord(c)] for c in explicit_mod.CLOSE if ord(c) in cmap],
                # a base character may be anything the font can draw, kana
                # included (｜本気（マジ）), but never a delimiter
                "base": sorted(set(cmap.values()) - delims, key=glyph_order.__getitem__),
                "ruby": [cmap[ord(c)] for c in ruby_alpha],
            },
            order=glyph_order,
            first_index=0,
            split={
                "base_max": explicit.base,
                "ruby_max": explicit.ruby,
                "cells": {n: [(explicit_mod.SPLIT_SIZE, x)
                              for x in explicit_mod.split_offsets(n)]
                          for n in range(1, explicit.ruby + 1)},
                "ruby": {cell: {cmap[ord(c)]: variant_name(c, *cell)
                                for c in ruby_alpha
                                if variant_name(c, *cell) in font["glyf"].glyphs}
                         for cell in explicit_mod.split_cells(explicit)},
                "coverage": {
                    "mark": [cmap[ord(c)] for c in explicit_mod.SPLIT_MARK
                             if ord(c) in cmap],
                    "open": [cmap[ord(c)] for c in explicit_mod.SPLIT_OPEN
                             if ord(c) in cmap],
                    "close": [cmap[ord(c)] for c in explicit_mod.SPLIT_CLOSE
                              if ord(c) in cmap],
                    "base": sorted(set(cmap.values()) - delims,
                                   key=glyph_order.__getitem__),
                    # ideographs only: this is what lets the marker be omitted
                    "kanji": sorted(
                        {cmap[ord(c)] for c in kanji_repertoire(base_path)
                         if ord(c) in cmap} - delims,
                        key=glyph_order.__getitem__),
                    "ruby": [cmap[ord(c)] for c in ruby_alpha],
                },
            },
        )
        ex_info = explicit_mod.cost(ruby_alpha, explicit, policy, explicit_grid)
        ex_info["protected_glyphs"] = len(protect)
        ex_info["lookups"] = len(explicit_lookups)

    n_ex = len(explicit_lookups)
    rules_by_first: dict[str, list[tuple[list[str], int]]] = defaultdict(list)
    for base, seq, out, _ in prepared:
        rules_by_first[seq[0]].append((seq, ms_index[(base, out)] + n_ex))
    # longest-first inside each ruleset -- this is what makes 日本語 beat 日本
    for v in rules_by_first.values():
        v.sort(key=lambda x: -len(x[0]))

    glyph_order = {g: i for i, g in enumerate(font.getGlyphOrder())}
    chain_lookups = gsub_mod.build_chain_lookup(rules_by_first, glyph_order)

    # Vertical writing: ruby offsets are baked into the outlines as horizontal
    # displacements, which is meaningless once the line runs top-to-bottom.
    # Rather than scatter ruby across the column, blank it out under vert/vrt2
    # and carry the base font's punctuation rotations across.
    vert_mapping = dict(vert_map)
    vert_mapping.update({g: blank for g in new_glyphs if g.startswith("r.")})
    vert_lookup = gsub_mod.build_single_subst_lookup(vert_mapping)

    # Explicit ruby first, then the MultipleSubst block, then the lexical
    # chain: lookups run in LookupList order, and explicit ruby has to claim
    # its base span (swapping it for protected duplicates) before the lexical
    # lookup gets its pass. That ordering is what enforces "explicit beats
    # automatic"; see the note above on why it goes at the front rather than
    # in the middle.
    all_lookups = explicit_lookups + ms_lookups + chain_lookups + [vert_lookup]
    chain_indices = list(range(n_ex + n_ms, n_ex + n_ms + len(chain_lookups)))
    # only the expression lookup, the last of the explicit block, is wired into
    # the feature; the rest are reached through SubstLookupRecords
    ccmp_indices = ([n_ex - 1] if n_ex else []) + chain_indices
    vert_index = len(all_lookups) - 1
    gsub_table = gsub_mod.build_gsub(
        all_lookups,
        [("ccmp", ccmp_indices), ("vert", [vert_index]), ("vrt2", [vert_index])],
    )

    # Stats must be taken here: fontTools' overflow resolution rewrites the
    # subtable objects in place (promoting them to Extension lookups), after
    # which ChainSubRuleSet is no longer reachable on them.
    layout_stats = gsub_mod.stats(chain_lookups, ms_lookups)

    tbl = newTable("GSUB")
    tbl.table = gsub_table
    font["GSUB"] = tbl
    for t in ("GPOS", "GDEF"):
        if t in font:
            del font[t]
    t_gsub = time.time()

    # ---- metrics and naming ---------------------------------------------
    font["hhea"].ascent = ASCENT
    font["hhea"].descent = DESCENT
    font["hhea"].lineGap = 0
    os2 = font["OS/2"]
    os2.usWinAscent = ASCENT
    os2.usWinDescent = -DESCENT
    os2.sTypoAscender = ASCENT
    os2.sTypoDescender = DESCENT
    os2.sTypoLineGap = 0
    os2.fsSelection |= 1 << 7  # USE_TYPO_METRICS
    font["head"].yMax = max(font["head"].yMax, ASCENT)

    full = f"{family} Regular"
    ps = f"{family}-Regular"
    name = font["name"]
    for nid, val in ((1, family), (2, "Regular"), (4, full), (6, ps),
                     (16, family), (17, "Regular")):
        name.setName(val, nid, 3, 1, 0x409)
        name.setName(val, nid, 1, 0, 0)
    name.setName(
        "YomiFont. Readings from JMdict (CC BY-SA 4.0, EDRDG). "
        "Outlines from Noto Sans JP (SIL OFL 1.1).",
        10, 3, 1, 0x409,
    )
    name.setName("https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project",
                 11, 3, 1, 0x409)

    # Keep real glyph names: they make hb-shape output readable, which is what
    # the shaping tests assert on.  Costs ~15 bytes per glyph in `post`.
    if keep_glyph_names:
        font["post"].formatType = 2.0
        font["post"].glyphOrder = font.getGlyphOrder()
        font["post"].extraNames = []
        font["post"].mapping = {}
    else:
        font["post"].formatType = 3.0

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    font.save(out_path)
    t_save = time.time()

    st = layout_stats
    size = os.path.getsize(out_path)
    reopened = TTFont(out_path, lazy=True)
    table_sizes = {}
    with open(out_path, "rb") as fh:
        data = fh.read()
    for tag in reopened.reader.tables:
        entry = reopened.reader.tables[tag]
        table_sizes[tag] = entry.length

    info = {
        "rules_in": len(rules),
        "rules_compiled": len(prepared),
        "rules_dropped": dropped,
        "glyphs": font["maxp"].numGlyphs,
        "ruby_glyphs": len(new_glyphs),
        "ruby_kana": len({k for k, _, _ in ruby_needed}),
        "ruby_sizes": sorted({s for _, s, _ in ruby_needed}),
        "block_rules": sum(1 for r in rules if not r.groups),
        "font_bytes": size,
        "gsub_bytes": table_sizes.get("GSUB", 0),
        "glyf_bytes": table_sizes.get("glyf", 0),
        "build_seconds": round(t_save - t0, 2),
        "explicit": ex_info,
        "timing": {
            "subset": round(t_subset - t0, 2),
            "ruby": round(t_ruby - t_subset, 2),
            "gsub": round(t_gsub - t_ruby, 2),
            "save": round(t_save - t_gsub, 2),
        },
        **st,
    }
    if verbose:
        print(f"[build] {out_path}")
        for k in ("rules_in", "rules_compiled", "rules_dropped", "glyphs",
                  "ruby_glyphs", "ruby_kana", "ruby_sizes", "block_rules",
                  "chain_rules", "chain_subtables",
                  "chain_first_glyphs", "multiple_subst_lookups",
                  "multiple_subst_mappings"):
            print(f"         {k:26s} {info[k]}")
        if ex_info:
            print(f"         {'explicit ruby':26s} base<={ex_info['base_max']} "
                  f"ruby<={ex_info['ruby_max']} grid={ex_info['grid']} "
                  f"alphabet={ex_info['alphabet']} -> {ex_info['expressions']} rules, "
                  f"{ex_info['ruby_glyphs']} glyphs, "
                  f"{ex_info['protected_glyphs']} protected")
        print(f"         {'font size':26s} {size/1e6:.2f} MB "
              f"(GSUB {info['gsub_bytes']/1e6:.2f} MB, glyf {info['glyf_bytes']/1e6:.2f} MB)")
        print(f"         {'build time':26s} {info['build_seconds']}s  {info['timing']}")
    return info
