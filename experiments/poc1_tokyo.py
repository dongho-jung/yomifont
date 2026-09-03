#!/usr/bin/env python3
"""PoC 1 / PoC 2 / PoC 3 / PoC 4 combined architectural checkpoint.

Question under test
-------------------
Can we produce visible furigana above kanji, using ONLY

    * GSUB MultipleSubst nested inside a ChainContextSubst
    * reusable ruby-kana glyphs (no per-word composite glyphs)
    * zero GPOS

while leaving the Unicode text untouched?

Mechanism
---------
For a word whose base span is M full-width chars with a reading of N ruby kana,
the i-th ruby kana must be drawn at

    x_i = (M*EM - N*RUBY_ADV)/2 + i*RUBY_ADV
        = 250 * (2M - N + 2i)          (EM=1000, RUBY_ADV=500)

so the horizontal placement depends only on the integer

    t = 2M - N + 2i

We therefore create, for each ruby kana K and each needed t, a *zero-advance*
glyph  r.K.t<t>  which is a nested TrueType composite:

    rk.K            = composite(base kana K, scale 0.5, offset 0/0)
    r.K.t<t>        = composite(rk.K,        scale 1.0, offset 250*t / RUBY_Y)

The nesting keeps every non-zero offset at scale 1.0, which side-steps the
SCALED_COMPONENT_OFFSET / UNSCALED_COMPONENT_OFFSET ambiguity between the
Apple and Microsoft rasterizer conventions.

GSUB then does, e.g. for 東京 -> とうきょう (M=2, N=5):

    ccmp:  sub uni6771' lookup L uni4EAC ;
    L:     sub uni6771 by r.to.t-1 r.u.t1 r.kyo.t3 r.o.t5 r.u.t7 uni6771 ;
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphComponent
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools import subset

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE = os.path.join(ROOT, "data/raw/NotoSansJP-Regular.ttf")
OUT = os.path.join(ROOT, "build/poc1.ttf")

EM = 1000
RUBY_SCALE = 0.5
RUBY_ADV = int(EM * RUBY_SCALE)  # 500
RUBY_Y = 900
ASCENT = 1320

# ---------------------------------------------------------------- test corpus
# (surface, [(base_span_start, base_span_len, reading)])
# base_span_* are indices into the surface string.
WORDS = [
    ("東京", [(0, 2, "とうきょう")]),
    ("京都", [(0, 2, "きょうと")]),
    ("今日", [(0, 2, "きょう")]),
    ("日本", [(0, 2, "にほん")]),
    ("日本語", [(0, 3, "にほんご")]),
    ("日本人", [(0, 3, "にほんじん")]),
    ("行く", [(0, 1, "い")]),
    ("行う", [(0, 1, "おこな")]),
    ("食べる", [(0, 1, "た")]),
    ("大人", [(0, 2, "おとな")]),
    ("勉強", [(0, 2, "べんきょう")]),
    ("昨日", [(0, 2, "きのう")]),
    ("取り戻す", [(0, 1, "と"), (2, 1, "もど")]),
]


def kana_name(ch: str) -> str:
    return "uni%04X" % ord(ch)


def collect_chars() -> set[str]:
    chars = set("。、 ")
    for surface, groups in WORDS:
        chars |= set(surface)
        for _, _, reading in groups:
            chars |= set(reading)
    return chars


def make_subset(chars: set[str]) -> TTFont:
    """Cut Noto Sans JP down to just what the PoC needs (fast iteration)."""
    opts = subset.Options()
    opts.layout_features = []
    opts.glyph_names = True
    opts.notdef_outline = True
    opts.recalc_bounds = True
    opts.drop_tables += ["BASE", "STAT", "vhea", "vmtx", "gasp", "prep", "fpgm", "cvt "]
    font = TTFont(BASE)
    subsetter = subset.Subsetter(options=opts)
    subsetter.populate(text="".join(sorted(chars)))
    subsetter.subset(font)
    return font


def add_ruby_glyphs(font: TTFont, needed: dict[str, set[int]]) -> None:
    """needed maps ruby kana char -> set of t values."""
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    cmap = font.getBestCmap()
    order = font.getGlyphOrder()
    new_names = []

    for ch in sorted(needed):
        src = cmap[ord(ch)]
        half = "rk.%04X" % ord(ch)
        g = Glyph()
        g.numberOfContours = -1
        comp = GlyphComponent()
        comp.glyphName = src
        comp.x, comp.y = 0, 0
        comp.flags = 0
        comp.transform = [[RUBY_SCALE, 0], [0, RUBY_SCALE]]
        g.components = [comp]
        glyf.glyphs[half] = g
        hmtx.metrics[half] = (0, 0)
        new_names.append(half)

        for t in sorted(needed[ch]):
            name = "r.%04X.t%+d" % (ord(ch), t)
            g2 = Glyph()
            g2.numberOfContours = -1
            c2 = GlyphComponent()
            c2.glyphName = half
            c2.x, c2.y = int(round(250 * t)), RUBY_Y
            c2.flags = 0
            c2.transform = [[1, 0], [0, 1]]
            g2.components = [c2]
            glyf.glyphs[name] = g2
            hmtx.metrics[name] = (0, 0)
            new_names.append(name)

    font.setGlyphOrder(order + new_names)
    font["maxp"].numGlyphs = len(font.getGlyphOrder())

    # CRITICAL: a TrueType rasterizer re-origins a glyph outline by
    # (lsb - xMin) -- see FreeType TT_Process_Simple_Glyph, which translates
    # by -pp1.x where pp1.x = bbox.xMin - left_bearing.  Our ruby glyphs carry
    # their horizontal placement *inside* the outline, so lsb MUST equal xMin
    # or the whole baked offset is silently thrown away.
    for name in new_names:
        glyf.glyphs[name].recalcBounds(glyf)
        adv, _ = hmtx.metrics[name]
        hmtx.metrics[name] = (adv, glyf.glyphs[name].xMin)

    font["post"].formatType = 2.0
    font["post"].glyphOrder = font.getGlyphOrder()
    font["post"].extraNames = []
    font["post"].mapping = {}


def ruby_glyph(ch: str, t: int) -> str:
    return "r.%04X.t%+d" % (ord(ch), t)


def build_rules(cmap):
    """Return (fea_text, needed_ruby)."""
    needed: dict[str, set[int]] = {}
    lookups = []
    rules = []

    # longest first so that 日本語 beats 日本
    words = sorted(WORDS, key=lambda w: -len(w[0]))

    for idx, (surface, groups) in enumerate(words):
        seq = [cmap[ord(c)] for c in surface]

        # ONE MultipleSubst, always at sequence index 0, carrying the ruby of
        # *every* group in the word.  Multiple glyph-inserting lookup records
        # in a single context rule are not portable: after the first record
        # changes the glyph count, HarfBuzz rewrites match_positions so later
        # sequenceIndex values point at the wrong glyph, and engines disagree
        # about whether they should.  Emitting everything from index 0 removes
        # the ambiguity entirely.
        outs = []
        for start, span, reading in groups:
            M = span
            N = len(reading)
            for i, k in enumerate(reading):
                # absolute offset from the start of the word, in 1/4 em units
                t = 4 * start + 2 * M - N + 2 * i
                needed.setdefault(k, set()).add(t)
                outs.append(ruby_glyph(k, t))

        base = seq[0]
        lkname = "mkr_%d" % idx
        lookups.append(
            "lookup %s {\n    sub %s by %s %s;\n} %s;\n"
            % (lkname, base, " ".join(outs), base, lkname)
        )

        # every glyph of the word is part of the *input* sequence so that the
        # match consumes the whole word (this is what gives longest-match its
        # teeth); the lookup is attached at position 0.
        marked = ["%s' lookup %s" % (seq[0], lkname)]
        marked += ["%s'" % g for g in seq[1:]]
        rules.append("    sub %s;" % " ".join(marked))

    fea = "\n".join(lookups)
    fea += "\nfeature ccmp {\n" + "\n".join(rules) + "\n} ccmp;\n"
    # also register for the CJK scripts explicitly
    return fea, needed


def main():
    chars = collect_chars()
    font = make_subset(chars)
    cmap = font.getBestCmap()
    fea, needed = build_rules(cmap)
    add_ruby_glyphs(font, needed)

    n_ruby = sum(1 + len(v) for v in needed.values())
    print(f"ruby kana inventory: {len(needed)} kana, {n_ruby} glyphs total")

    open(os.path.join(ROOT, "build/poc1.fea"), "w").write(fea)
    addOpenTypeFeaturesFromString(font, fea)

    # vertical metrics: make room for the ruby
    font["hhea"].ascent = ASCENT
    font["OS/2"].usWinAscent = ASCENT
    font["OS/2"].sTypoAscender = ASCENT
    font["head"].yMax = max(font["head"].yMax, ASCENT)

    n = font["name"]
    for nid, val in ((1, "YomiFont PoC1"), (4, "YomiFont PoC1"), (6, "YomiFontPoC1-Regular")):
        n.setName(val, nid, 3, 1, 0x409)
        n.setName(val, nid, 1, 0, 0)

    font.save(OUT)
    print("wrote", OUT, os.path.getsize(OUT), "bytes,", font["maxp"].numGlyphs, "glyphs")


if __name__ == "__main__":
    main()
