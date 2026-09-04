#!/usr/bin/env python3
"""EXPERIMENT: explicit ruby that survives Blink's run split.

    PYTHONPATH=src ./tests/integration/make_split_font.py dist/SplitProto.ttf
    open http://127.0.0.1:8777/tests/integration/split_demo.html

Not shipped. This is the prototype behind the claim in explicit-ruby.md that a
kanji base IS reachable in Blink, and it exists so that claim can be re-checked
rather than believed.

Blink hands the shaper two buffers and no rule sees both:

    ｜月（   |   ライト）

Run 1 knows the base but not the reading; run 2 knows the reading but not how
wide the base was. The shipped design needs both at once, which is why a kanji
base gets nothing in Chrome. Split the rules in two and each half works inside
its own run:

    run 1   ｜BASE（     hide the delimiters, keep the base
    run 2   RUBY）｜     hide the close and the marker, set the kana

Two things make it work, and one thing it cannot do.

**The trailing marker is not decoration.** Without it run 2's rule is
`KANA+ CLOSE`, which is also what ordinary parenthesised kana looks like --
私（わたし）, （ですます） -- and swallowing those is not acceptable. The marker
has to sit *after* a kana so it joins run 2; a Common character before the kana
joins the Han run instead.

**Ruby is right-aligned to the end of the base, not centred.** Centring needs
the base width, and run 2 cannot be told it. It can be *moved* instead -- a
negative XAdvance on the last glyph of run 1 shifts where run 2 starts, and
Chrome honours that across the boundary (tests/integration/shift_probe.html).
But whatever run 1 subtracts, something has to add back to keep the line
correct, and only run 1 knows how much. So the shift buys nothing: run 2's
origin is necessarily the base end, and the ruby grows leftward from there.

**Known defect.** Run 1's rule needs the leading ｜, and ｜ is Script=Common, so
after kana it is absorbed into the preceding run and run 1 never matches. The
ruby still draws (run 2 is unaffected), so the expression renders half-done:
reading present, delimiters visible. Fixing it needs a marker that is not
Common -- which means an ideograph, and an ugly syntax.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "src")

from fontTools import subset
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables as ot
from fontTools.ttLib.tables._g_l_y_f import Glyph

from yomifont import gsub as gsub_mod
from yomifont.build import ASCENT, DESCENT
from yomifont.layout import EM
from yomifont.rubyglyphs import RUBY_Y, add_blank_glyph, add_ruby_glyphs, variant_name

BASE_FONT = "data/raw/NotoSansJP-Regular.ttf"
RUBY_SRC = "data/raw/NotoSansJP-w500.ttf"
START, OPEN, CLOSE = "｜|", "（(", "）)"
BMAX, NMAX = 8, 16
SIZE = 0.5
PITCH = int(SIZE * EM)          # 500: kana are never set closer than their advance
GRID = 100

ALPHA = "".join(sorted(set(
    "ライトそらマジともとうきょうにほんごのりょくしけんエドあいうえおかきくけこ"
    "さしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをんー"
    "ダークネスブレイヤガギグゲゴザジズゼゾバビブベボパピプペポ")))
BASES = "".join(sorted(set("月宇宙本気強敵東京日本語能力試験超絶暗黒剣新宿区未知語猫犬阿")))


def offsets(n: int) -> list[int]:
    """Left edge of each kana, right-aligned to the origin (= the base end).

    Centring on the base would need the base width, and run 2 cannot learn it:
    whatever run 1 subtracts from the pen, something has to add back, and only
    run 1 knows how much. Right-aligning needs nothing from run 1 at all -- the
    ruby simply grows leftward from where run 2 starts -- and the expression
    keeps its exact advance.
    """
    return [-(n - i) * PITCH for i in range(n)]


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "dist/SplitProto.ttf"
    font = TTFont(BASE_FONT)
    opts = subset.Options()
    opts.layout_features = []
    opts.glyph_names = True
    opts.notdef_outline = True
    ss = subset.Subsetter(options=opts)
    ss.populate(text=START + OPEN + CLOSE + ALPHA + BASES + "、。を見た昨")
    ss.subset(font)
    cmap = font.getBestCmap()

    cells = {(SIZE, x) for n in range(1, NMAX + 1) for x in offsets(n)}
    add_ruby_glyphs(font, {(c, s, x) for c in ALPHA for s, x in cells},
                    ruby_y=RUBY_Y, source_path=RUBY_SRC)
    blank = add_blank_glyph(font)

    # one zero-advance carrier per base length; GPOS gives it the negative
    # advance that pulls run 2 back to the centre of the base
    glyf, hmtx = font["glyf"], font["hmtx"]
    order = list(font.getGlyphOrder())
    shifts = []
    for b in range(1, BMAX + 1):
        name = f"shift.{b}"
        g = Glyph(); g.numberOfContours = 0
        g.xMin = g.yMin = g.xMax = g.yMax = 0
        glyf.glyphs[name] = g
        hmtx.metrics[name] = (0, 0)
        if "vmtx" in font:
            font["vmtx"].metrics[name] = (1000, 0)
        shifts.append(name)
    font.setGlyphOrder(order + shifts)
    font["maxp"].numGlyphs = len(font.getGlyphOrder())

    go = {n: i for i, n in enumerate(font.getGlyphOrder())}
    cov = lambda cs: gsub_mod._coverage([cmap[ord(c)] for c in cs], go)
    delims = {cmap[ord(c)] for c in START + OPEN + CLOSE}

    hide = gsub_mod.build_single_subst_lookup({g: blank for g in delims},
                                              extension=True)
    protect_map = {cmap[ord(c)]: cmap[ord(c)] for c in BASES}   # no automatic side here
    lookups = [hide]
    open_to_shift = []
    for b in range(1, BMAX + 1):
        m = {cmap[ord(c)]: f"shift.{b}" for c in OPEN}
        lookups.append(gsub_mod.build_single_subst_lookup(m, extension=True))
        open_to_shift.append(len(lookups) - 1)
    ruby_idx = {}
    for cell in sorted(cells):
        m = {cmap[ord(c)]: variant_name(c, *cell) for c in ALPHA
             if variant_name(c, *cell) in glyf.glyphs}
        ruby_idx[cell] = len(lookups)
        lookups.append(gsub_mod.build_single_subst_lookup(m, extension=True))

    subs = []
    # run 1: ｜ BASE{b} （   ->  blank, (base kept), shift.b
    for b in range(1, BMAX + 1):
        st = ot.ChainContextSubst(); st.Format = 3
        st.BacktrackGlyphCount = 0; st.BacktrackCoverage = []
        st.LookAheadGlyphCount = 0; st.LookAheadCoverage = []
        st.InputCoverage = [cov(START)] + [cov(BASES + ALPHA)] * b + [cov(OPEN)]
        st.InputGlyphCount = len(st.InputCoverage)
        st.SubstLookupRecord = []
        for idx, lk in ((0, 0), (b + 1, 0)):
            r = ot.SubstLookupRecord(); r.SequenceIndex = idx; r.LookupListIndex = lk
            st.SubstLookupRecord.append(r)
        st.SubstCount = len(st.SubstLookupRecord)
        subs.append(st)
    # run 2: RUBY{n} ）   ->  positioned kana, blank
    for n in range(1, NMAX + 1):
        st = ot.ChainContextSubst(); st.Format = 3
        st.BacktrackGlyphCount = 0; st.BacktrackCoverage = []
        st.LookAheadGlyphCount = 0; st.LookAheadCoverage = []
        st.InputCoverage = [cov(ALPHA)] * n + [cov(CLOSE)] + [cov(START)]
        st.InputGlyphCount = len(st.InputCoverage)
        st.SubstLookupRecord = []
        for i, x in enumerate(offsets(n)):
            r = ot.SubstLookupRecord(); r.SequenceIndex = i
            r.LookupListIndex = ruby_idx[(SIZE, x)]
            st.SubstLookupRecord.append(r)
        for k in (n, n + 1):
            r = ot.SubstLookupRecord(); r.SequenceIndex = k; r.LookupListIndex = 0
            st.SubstLookupRecord.append(r)
        st.SubstCount = len(st.SubstLookupRecord)
        subs.append(st)
    subs.sort(key=lambda s: -s.InputGlyphCount)

    lk = ot.Lookup(); lk.LookupType = 7; lk.LookupFlag = 0
    lk.SubTable = [gsub_mod._extend(s, 6) for s in subs]
    lk.SubTableCount = len(lk.SubTable)
    lookups.append(lk)
    gsub = gsub_mod.build_gsub(lookups, [("ccmp", [len(lookups) - 1])])
    t = newTable("GSUB"); t.table = gsub; font["GSUB"] = t

    # GPOS: shift.b carries -b*EM/2
    pos = []
    for b in range(1, BMAX + 1):
        st = ot.SinglePos(); st.Format = 1
        st.Coverage = ot.Coverage(); st.Coverage.glyphs = [f"shift.{b}"]
        st.Value = ot.ValueRecord(); st.Value.XAdvance = -(b * EM) // 2
        st.ValueFormat = 0x0004
        l = ot.Lookup(); l.LookupType = 1; l.LookupFlag = 0
        l.SubTable = [st]; l.SubTableCount = 1
        pos.append(l)
    gpos = ot.GPOS(); gpos.Version = 0x00010000
    ll = ot.LookupList(); ll.Lookup = pos; ll.LookupCount = len(pos)
    gpos.LookupList = ll
    recs = []
    for tag in ("dist", "kern", "mark"):
        f = ot.Feature(); f.FeatureParams = None
        f.LookupListIndex = list(range(len(pos))); f.LookupCount = len(pos)
        rec = ot.FeatureRecord(); rec.FeatureTag = tag; rec.Feature = f
        recs.append(rec)
    fl = ot.FeatureList(); fl.FeatureRecord = recs; fl.FeatureCount = len(recs)
    gpos.FeatureList = fl
    srs = []
    for tag in ("DFLT", "hani", "kana", "latn"):
        ls = ot.LangSys(); ls.LookupOrder = None; ls.ReqFeatureIndex = 0xFFFF
        ls.FeatureIndex = list(range(len(recs))); ls.FeatureCount = len(recs)
        sc = ot.Script(); sc.DefaultLangSys = ls; sc.LangSysRecord = []; sc.LangSysCount = 0
        sr = ot.ScriptRecord(); sr.ScriptTag = tag; sr.Script = sc
        srs.append(sr)
    sl = ot.ScriptList(); sl.ScriptRecord = srs; sl.ScriptCount = len(srs)
    gpos.ScriptList = sl
    t = newTable("GPOS"); t.table = gpos; font["GPOS"] = t

    font["hhea"].ascent = ASCENT; font["hhea"].descent = DESCENT; font["hhea"].lineGap = 0
    o2 = font["OS/2"]; o2.usWinAscent, o2.usWinDescent = ASCENT, -DESCENT
    o2.sTypoAscender, o2.sTypoDescender, o2.sTypoLineGap = ASCENT, DESCENT, 0
    o2.fsSelection |= 1 << 7
    font["head"].yMax = max(font["head"].yMax, ASCENT)
    for nid, v in ((1, "SplitProto"), (4, "SplitProto"), (6, "SplitProto")):
        font["name"].setName(v, nid, 3, 1, 0x409)
    font["post"].formatType = 2.0
    font["post"].glyphOrder = font.getGlyphOrder()
    font["post"].extraNames = []; font["post"].mapping = {}
    font.save(out)
    print(f"wrote {out}: {font['maxp'].numGlyphs} glyphs, {len(subs)} rules, "
          f"{len(cells)} (size,offset) cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
