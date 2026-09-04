"""GSUB construction for YomiFont.

Shape of the table
------------------
    feature ccmp
      -> Lookup C : ChainContextSubst, Format 1, split across N subtables
           coverage      = every character that can start a rule
           ChainSubRule  = the whole word as *input* (so the match consumes it
                           and longest-match works), with a single
                           SequenceLookupRecord at index 0
      -> Lookup M0..Mk : MultipleSubst
           base glyph -> [ruby glyphs..., base glyph]

Why one record at index 0
-------------------------
A context rule may carry several SequenceLookupRecords, and it is tempting to
attach one MultipleSubst per ruby group (取 and 戻 in 取り戻す).  Do not: as
soon as the first record changes the glyph count, HarfBuzz rewrites
match_positions so later sequenceIndex values address different glyphs, and
engines disagree about whether they should.  Emitting *all* of a word's ruby
from index 0, with per-group offsets folded into the ruby glyph's t value, has
one record per rule and no ambiguity.  (Measured: with two records, 取り戻す
silently lost its second ruby group under HarfBuzz.)

Why the whole word is input
---------------------------
Marking every character of the word as input (rather than first-char input +
lookahead) makes the lookup consume the whole match, so scanning resumes after
語 in 日本語 instead of re-entering at 本.

Longest match
-------------
Rules inside one ChainSubRuleSet are tried in order, so they are emitted
longest-first.  All rules starting with the same character therefore have to
live in the same subtable, or a shorter rule in an earlier subtable would win.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from fontTools.ttLib.tables import otTables as ot

# Keep each ChainContextSubst subtable comfortably inside the 64 kB reach of
# its internal Offset16 fields.  fontTools can repair overflows after the fact,
# but splitting up front keeps the output deterministic.
SUBTABLE_BUDGET = 48_000


def _coverage(glyphs: list[str], order: dict[str, int]) -> ot.Coverage:
    # Coverage tables must be sorted by glyph ID.  fontTools will re-sort and
    # warn, but that would silently desynchronise the parallel
    # ChainSubRuleSet array, so we sort both together here.
    cov = ot.Coverage()
    cov.glyphs = sorted(glyphs, key=order.__getitem__)
    return cov


def build_multiple_subst_lookups(
    pairs: list[tuple[str, tuple[str, ...]]],
) -> tuple[list[ot.Lookup], dict[tuple[str, tuple[str, ...]], int]]:
    """Bin-pack (base glyph -> output sequence) mappings into lookups.

    A MultipleSubst subtable is a map keyed by glyph, so it can hold at most one
    output per glyph.  The number of lookups needed is therefore exactly
    max over glyphs of (number of distinct outputs for that glyph); the packing
    below achieves that bound.
    """
    by_glyph: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for g, out in pairs:
        if (g, out) in seen:
            continue
        seen.add((g, out))
        by_glyph[g].append(out)

    n_lookups = max((len(v) for v in by_glyph.values()), default=0)
    tables: list[dict[str, list[str]]] = [dict() for _ in range(n_lookups)]
    index: dict[tuple[str, tuple[str, ...]], int] = {}
    for g, outs in by_glyph.items():
        # deterministic order
        for i, out in enumerate(sorted(outs)):
            tables[i][g] = list(out)
            index[(g, out)] = i

    lookups = []
    for mapping in tables:
        st = ot.MultipleSubst()
        st.Format = 1
        st.mapping = mapping
        lk = ot.Lookup()
        lk.LookupType = 7
        lk.LookupFlag = 0
        lk.SubTable = [_extend(st, 2)]
        lk.SubTableCount = 1
        lookups.append(lk)
    return lookups, index


def _rule_size(seq_len: int) -> int:
    # offset in the ruleset + backtrack(2) + input count(2) + (seq_len-1)*2
    # + lookahead(2) + substCount(2) + one 4-byte record
    return 2 + 2 + 2 + (seq_len - 1) * 2 + 2 + 2 + 4


def build_chain_lookup(
    rules_by_first: dict[str, list[tuple[list[str], int]]],
    glyph_order: dict[str, int],
) -> list[ot.Lookup]:
    """One ChainContextSubst lookup, split into as many subtables as needed.

    `rules_by_first` maps first glyph -> [(glyph sequence, multiple-subst lookup
    index)], already ordered longest-first.
    """
    subtables: list[ot.ChainContextSubst] = []
    cur: list[tuple[str, ot.ChainSubRuleSet]] = []
    cur_size = 12

    def flush():
        nonlocal cur, cur_size
        if not cur:
            return
        cur.sort(key=lambda gs: glyph_order[gs[0]])
        st = ot.ChainContextSubst()
        st.Format = 1
        st.Coverage = _coverage([g for g, _ in cur], glyph_order)
        st.ChainSubRuleSet = [s for _, s in cur]
        st.ChainSubRuleSetCount = len(cur)
        subtables.append(st)
        cur, cur_size = [], 12

    for first in sorted(rules_by_first, key=glyph_order.__getitem__):
        entries = rules_by_first[first]
        ruleset = ot.ChainSubRuleSet()
        ruleset.ChainSubRule = []
        size = 2
        for seq, lookup_idx in entries:
            r = ot.ChainSubRule()
            r.Backtrack = []
            r.BacktrackGlyphCount = 0
            r.Input = list(seq[1:])          # first glyph comes from Coverage
            r.InputGlyphCount = len(seq)
            r.LookAhead = []
            r.LookAheadGlyphCount = 0
            rec = ot.SubstLookupRecord()
            rec.SequenceIndex = 0
            rec.LookupListIndex = lookup_idx
            r.SubstLookupRecord = [rec]
            r.SubstCount = 1
            ruleset.ChainSubRule.append(r)
            size += _rule_size(len(seq))
        ruleset.ChainSubRuleCount = len(ruleset.ChainSubRule)

        # all rules for one first glyph must stay together, otherwise a shorter
        # rule in an earlier subtable would beat a longer one in a later subtable
        if cur and cur_size + size + 2 > SUBTABLE_BUDGET:
            flush()
        cur.append((first, ruleset))
        cur_size += size + 2 + 2  # ruleset offset + coverage entry
    flush()

    if not subtables:
        # No lexical rules at all (an explicit-ruby-only build). A Lookup with
        # zero subtables is not something a validator has to accept, so emit
        # nothing and let the caller wire up an empty feature.
        return []

    lk = ot.Lookup()
    lk.LookupType = 7
    lk.LookupFlag = 0
    lk.SubTable = [_extend(st, 6) for st in subtables]
    lk.SubTableCount = len(lk.SubTable)
    return [lk]


# A SingleSubst format 2 subtable stores its substitutes inline and reaches its
# Coverage through an Offset16 that has to clear them:
#
#     SubstFormat(2) coverageOffset(2) glyphCount(2) substituteGlyphIDs(2N)
#
# so the Coverage lands at 6 + 2N and the subtable cannot hold much more than
# 32,765 mappings -- and rather less once anything else is packed in between.
# fontTools cannot rescue this ("Don't know how to split GSUB lookup type 1"),
# so the split has to happen here. It bites on the vert/vrt2 lookup, which maps
# every ruby glyph to a blank: 14k of them without explicit ruby, 44k with it.
#
# Subtables of one lookup are tried in order and cover disjoint glyphs, so
# splitting is exactly equivalent.
MAX_SINGLE_SUBST = 16_000


def build_single_subst_lookup(mapping: dict[str, str],
                              extension: bool = False) -> ot.Lookup:
    items = sorted(mapping.items())
    chunks = [dict(items[i:i + MAX_SINGLE_SUBST])
              for i in range(0, max(len(items), 1), MAX_SINGLE_SUBST)] or [{}]
    subtables = []
    for chunk in chunks:
        st = ot.SingleSubst()
        st.Format = 2
        st.mapping = chunk
        subtables.append(_extend(st, 1) if extension else st)
    lk = ot.Lookup()
    lk.LookupFlag = 0
    lk.LookupType = 7 if extension else 1
    lk.SubTable = subtables
    lk.SubTableCount = len(subtables)
    return lk


def _extend(subtable, lookup_type: int):
    """Wrap a subtable in an Extension (LookupType 7) record.

    Extension replaces the Offset16 from a Lookup to its subtable with an
    Offset32.  fontTools will do this on its own when a LookupList overflows,
    but only by compiling the whole table, catching the overflow, promoting one
    lookup and compiling again -- which on a GSUB this size is minutes of
    repair.  Doing it up front makes the packing deterministic and the build
    fast, and it is what large CJK fonts ship anyway.

    It is *not* what makes explicit ruby compile.  That was a SingleSubst
    overflow with a different cause; see MAX_SINGLE_SUBST.
    """
    ext = ot.ExtensionSubst()
    ext.Format = 1
    ext.ExtensionLookupType = lookup_type
    ext.ExtSubTable = subtable
    return ext


def build_explicit_lookups(
    placements: dict[tuple[int, int], list[tuple[float, int]]],
    hide: dict[str, str],
    protect: dict[str, str],
    ruby: dict[tuple[float, int], dict[str, str]],
    coverage: dict[str, list[str]],
    order: dict[str, int],
    first_index: int,
    split: dict | None = None,
) -> list[ot.Lookup]:
    """Explicit Ruby: one ChainContextSubst rule per expression *shape*.

    `placements` maps (base length, ruby length) -> the (size, offset) each ruby
    character needs; see `explicit`.  The returned lookups are appended to the
    LookupList starting at `first_index`, and the expression lookup is last.

    Format 3 (coverage per position) rather than Format 2 (classes) because a
    kana has to be admissible in *both* the base and the ruby span -- ｜本気
    （マジ）has kana on one side and ｜そら（ソラ）on both -- and a ClassDef can
    only put a glyph in one class.  Coverage tables are sets, so the fullwidth
    and ASCII delimiters cost nothing extra, and fontTools interns the
    identical ones so the shared BASE coverage is written once.

    Every SubstLookupRecord is a SingleSubst, so the glyph count never changes
    and later sequence indices stay addressable -- the failure this module's
    header warns about only bites when a record inserts or removes glyphs.
    """
    # Extension everywhere in here: see `_extend`. The ruby lookups need it to
    # compile at all, and the other two are wrapped for consistency so the
    # block has no Offset16 reaching across it.
    lookups: list[ot.Lookup] = [build_single_subst_lookup(hide, extension=True)]
    hide_idx = first_index
    protect_idx = first_index + 1
    lookups.append(build_single_subst_lookup(protect, extension=True))

    ruby_idx: dict[tuple[float, int], int] = {}
    for cell in sorted(ruby):
        ruby_idx[cell] = first_index + len(lookups)
        lookups.append(build_single_subst_lookup(ruby[cell], extension=True))

    cov = {k: _coverage(v, order) for k, v in coverage.items()}
    subtables = []
    # Longest expressions first.  Nothing actually depends on it -- the open
    # and close delimiters pin B and N uniquely -- but subtable order is
    # priority order, so being explicit costs nothing and documents intent.
    for (b, n), cells in sorted(placements.items(), key=lambda kv: (-kv[0][0], -kv[0][1])):
        st = ot.ChainContextSubst()
        st.Format = 3
        st.BacktrackGlyphCount = 0
        st.BacktrackCoverage = []
        st.LookAheadGlyphCount = 0
        st.LookAheadCoverage = []
        st.InputCoverage = ([cov["start"]] + [cov["base"]] * b + [cov["open"]]
                            + [cov["ruby"]] * n + [cov["close"]])
        st.InputGlyphCount = len(st.InputCoverage)
        records = [(0, hide_idx), (b + 1, hide_idx), (b + n + 2, hide_idx)]
        records += [(1 + j, protect_idx) for j in range(b)]
        records += [(b + 2 + i, ruby_idx[cells[i]]) for i in range(n)]
        st.SubstLookupRecord = []
        for idx, lk_idx in sorted(records):
            rec = ot.SubstLookupRecord()
            rec.SequenceIndex = idx
            rec.LookupListIndex = lk_idx
            st.SubstLookupRecord.append(rec)
        st.SubstCount = len(st.SubstLookupRecord)
        subtables.append(st)

    # ---- the Blink fail-safe -------------------------------------------
    # Blink itemises before shaping and always starts a new run at a Han->Kana
    # boundary, so it never shows one rule the whole expression. Measured: the
    # *prefix* ｜BASE（ does survive as one run, because Script=Common
    # characters join the Han run (tests/integration/itemize_probe.html).
    #
    # Without this, Chrome renders ｜宇宙（そら） as visible markup *plus* the
    # automatic reading うちゅう -- a reading the author explicitly replaced.
    # These rules claim the base span on the strength of the prefix alone and
    # do nothing else: no delimiter is hidden and no ruby is emitted, so the
    # markup stays intact and the expression fails atomically.
    #
    # They come last. Subtables are tried in order, so wherever the full
    # expression matched it has already consumed the span and these never run.
    for b in range(1, max(b for b, _ in placements) + 1):
        st = ot.ChainContextSubst()
        st.Format = 3
        st.BacktrackGlyphCount = 0
        st.BacktrackCoverage = []
        st.LookAheadGlyphCount = 0
        st.LookAheadCoverage = []
        st.InputCoverage = [cov["start"]] + [cov["base"]] * b + [cov["open"]]
        st.InputGlyphCount = len(st.InputCoverage)
        st.SubstLookupRecord = []
        for j in range(b):
            rec = ot.SubstLookupRecord()
            rec.SequenceIndex = 1 + j
            rec.LookupListIndex = protect_idx
            st.SubstLookupRecord.append(rec)
        st.SubstCount = len(st.SubstLookupRecord)
        subtables.append(st)

    # ---- the split form ------------------------------------------------
    # Two rules that never have to see each other, so an engine that itemises
    # the text into runs can still match both -- one in each. This is what
    # makes a kanji base work in Blink; see `explicit.MARK`.
    #
    # They come after everything above. Where the whole expression did reach
    # one buffer, the single-run rule has already consumed it and these never
    # run, so engines that can do the better typography still do.
    split = split or {}
    if split:
        s_cov = split["coverage"]
        s_ruby = split["ruby"]
        s_idx: dict[tuple[float, int], int] = {}
        for cell in sorted(s_ruby):
            s_idx[cell] = first_index + len(lookups)
            lookups.append(build_single_subst_lookup(s_ruby[cell], extension=True))
        scov = {k: _coverage(v, order) for k, v in s_cov.items()}

        # run 1: BASE{b} ｜ （  -- base is the run of kanji before the marker
        for b in range(1, split["base_max"] + 1):
            st = ot.ChainContextSubst()
            st.Format = 3
            st.BacktrackGlyphCount = 0
            st.BacktrackCoverage = []
            st.LookAheadGlyphCount = 0
            st.LookAheadCoverage = []
            st.InputCoverage = ([scov["kanji"]] * b + [scov["mark"]]
                                + [scov["open"]])
            st.InputGlyphCount = len(st.InputCoverage)
            st.SubstLookupRecord = []
            for idx in range(b + 2):
                rec = ot.SubstLookupRecord()
                rec.SequenceIndex = idx
                rec.LookupListIndex = hide_idx if idx >= b else protect_idx
                st.SubstLookupRecord.append(rec)
            st.SubstCount = len(st.SubstLookupRecord)
            subtables.append(st)
        # There is deliberately no marker-less variant. `BASE{b} 《` would be
        # convenient -- Aozora allows it -- but the first run cannot see whether
        # a reading follows, so it would hide the 《 of any 漢字《…》 in ordinary
        # prose: 小説《ノルウェイの森》 came out as 小説ノルウェイの森》, with the
        # opening bracket gone and the closing one left. The marker is what
        # makes the intent visible inside the first run.
        # run 2: RUBY{n} ） ｜
        for n in range(1, split["ruby_max"] + 1):
            st = ot.ChainContextSubst()
            st.Format = 3
            st.BacktrackGlyphCount = 0
            st.BacktrackCoverage = []
            st.LookAheadGlyphCount = 0
            st.LookAheadCoverage = []
            st.InputCoverage = ([scov["ruby"]] * n + [scov["close"]]
                                + [scov["mark"]])
            st.InputGlyphCount = len(st.InputCoverage)
            st.SubstLookupRecord = []
            for i, cell in enumerate(split["cells"][n]):
                rec = ot.SubstLookupRecord()
                rec.SequenceIndex = i
                rec.LookupListIndex = s_idx[cell]
                st.SubstLookupRecord.append(rec)
            for k in (n, n + 1):
                rec = ot.SubstLookupRecord()
                rec.SequenceIndex = k
                rec.LookupListIndex = hide_idx
                st.SubstLookupRecord.append(rec)
            st.SubstCount = len(st.SubstLookupRecord)
            subtables.append(st)

    lk = ot.Lookup()
    lk.LookupType = 7
    lk.LookupFlag = 0
    lk.SubTable = [_extend(st, 6) for st in subtables]
    lk.SubTableCount = len(lk.SubTable)
    lookups.append(lk)
    return lookups


SCRIPTS = ["DFLT", "hani", "kana", "latn"]


def build_gsub(lookups: list[ot.Lookup],
               features: list[tuple[str, list[int]]]) -> ot.GSUB:
    """features is [(tag, [lookup indices])], emitted in the given order."""
    gsub = ot.GSUB()
    gsub.Version = 0x00010000

    lookup_list = ot.LookupList()
    lookup_list.Lookup = lookups
    lookup_list.LookupCount = len(lookups)
    gsub.LookupList = lookup_list

    # FeatureRecords must be ordered alphabetically by tag.
    features = sorted(features, key=lambda f: f[0])
    records = []
    for tag, indices in features:
        feature = ot.Feature()
        feature.FeatureParams = None
        feature.LookupListIndex = list(indices)
        feature.LookupCount = len(indices)
        frec = ot.FeatureRecord()
        frec.FeatureTag = tag
        frec.Feature = feature
        records.append(frec)
    flist = ot.FeatureList()
    flist.FeatureRecord = records
    flist.FeatureCount = len(records)
    gsub.FeatureList = flist

    all_indices = list(range(len(records)))
    script_records = []
    for tag in SCRIPTS:
        langsys = ot.LangSys()
        langsys.LookupOrder = None
        langsys.ReqFeatureIndex = 0xFFFF
        langsys.FeatureIndex = all_indices
        langsys.FeatureCount = len(all_indices)
        script = ot.Script()
        script.DefaultLangSys = langsys
        script.LangSysRecord = []
        script.LangSysCount = 0
        srec = ot.ScriptRecord()
        srec.ScriptTag = tag
        srec.Script = script
        script_records.append(srec)
    slist = ot.ScriptList()
    slist.ScriptRecord = script_records
    slist.ScriptCount = len(script_records)
    gsub.ScriptList = slist
    return gsub


def _inner(subtable):
    """Unwrap an Extension record; everything is wrapped now (see `_extend`)."""
    return getattr(subtable, "ExtSubTable", subtable)


def stats(chain_lookups: list[ot.Lookup], ms_lookups: list[ot.Lookup]) -> dict:
    chain_subs = [_inner(st) for lk in chain_lookups for st in lk.SubTable]
    n_rules = sum(len(rs.ChainSubRule)
                  for st in chain_subs for rs in st.ChainSubRuleSet)
    n_first = sum(len(st.Coverage.glyphs) for st in chain_subs)
    n_map = sum(len(_inner(st).mapping) for lk in ms_lookups for st in lk.SubTable)
    return {
        "chain_rules": n_rules,
        "chain_subtables": len(chain_subs),
        "chain_first_glyphs": n_first,
        "multiple_subst_lookups": len(ms_lookups),
        "multiple_subst_mappings": n_map,
    }
