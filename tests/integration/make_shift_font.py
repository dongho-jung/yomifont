#!/usr/bin/env python3
"""Can run 1 move run 2's origin?

    PYTHONPATH=src ./tests/integration/make_shift_font.py dist/Shift.ttf

Blink hands the shaper `｜月（` and `ライト）` as two buffers, so no GSUB rule
sees both.  The first buffer does know the base -- Script=Common characters
join the Han run, which is why `｜月（` is SAME_RUN.  What it cannot do is tell
the second buffer how wide that base was.

Unless it can move it.  Runs are laid out one after another, so if the last
glyph of run 1 carries a **negative advance** the next run starts further left.
A negative advance is impossible in `hmtx` (uint16) but ordinary in GPOS.  If
that works, run 1 can shift run 2's origin to the centre of the base, and run 2
can then place ruby knowing only how many kana it has -- which it can count.

This font tests only that one mechanism:

    U+FF5C  ｜   XAdvance -500  under `kern`
    U+FF08  （   XAdvance -500  under `dist`
    U+FF3B  ［   XAdvance -500  under `mark`

Three features, because engines differ on which GPOS features they run by
default.  Render 月｜ラ and see whether ラ moves left over 月.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fontTools import subset  # noqa: E402
from fontTools.ttLib import TTFont, newTable  # noqa: E402
from fontTools.ttLib.tables import otTables as ot  # noqa: E402

BASE_FONT = "data/raw/NotoSansJP-Regular.ttf"
SHIFT = -500
# (marker character, GPOS feature to hang it on)
MARKERS = [("｜", "kern"), ("（", "dist"), ("［", "mark")]
TEXT = "月ラつ" + "".join(m for m, _ in MARKERS)


def single_pos(glyph: str, order: dict) -> ot.Lookup:
    st = ot.SinglePos()
    st.Format = 1
    st.Coverage = ot.Coverage()
    st.Coverage.glyphs = [glyph]
    st.Value = ot.ValueRecord()
    st.Value.XAdvance = SHIFT
    st.ValueFormat = 0x0004          # XAdvance only
    lk = ot.Lookup()
    lk.LookupType = 1
    lk.LookupFlag = 0
    lk.SubTable = [st]
    lk.SubTableCount = 1
    return lk


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "dist/Shift.ttf"
    font = TTFont(BASE_FONT)
    opts = subset.Options()
    opts.layout_features = []
    opts.glyph_names = True
    opts.notdef_outline = True
    ss = subset.Subsetter(options=opts)
    ss.populate(text=TEXT)
    ss.subset(font)

    cmap = font.getBestCmap()
    order = {n: i for i, n in enumerate(font.getGlyphOrder())}

    lookups, features = [], []
    for ch, feat in MARKERS:
        lookups.append(single_pos(cmap[ord(ch)], order))
        features.append((feat, [len(lookups) - 1]))

    gpos = ot.GPOS()
    gpos.Version = 0x00010000
    ll = ot.LookupList()
    ll.Lookup = lookups
    ll.LookupCount = len(lookups)
    gpos.LookupList = ll
    features.sort(key=lambda f: f[0])
    records = []
    for tag, idx in features:
        f = ot.Feature()
        f.FeatureParams = None
        f.LookupListIndex = list(idx)
        f.LookupCount = len(idx)
        rec = ot.FeatureRecord()
        rec.FeatureTag = tag
        rec.Feature = f
        records.append(rec)
    fl = ot.FeatureList()
    fl.FeatureRecord = records
    fl.FeatureCount = len(records)
    gpos.FeatureList = fl
    scripts = []
    for tag in ("DFLT", "hani", "kana", "latn"):
        ls = ot.LangSys()
        ls.LookupOrder = None
        ls.ReqFeatureIndex = 0xFFFF
        ls.FeatureIndex = list(range(len(records)))
        ls.FeatureCount = len(records)
        sc = ot.Script()
        sc.DefaultLangSys = ls
        sc.LangSysRecord = []
        sc.LangSysCount = 0
        sr = ot.ScriptRecord()
        sr.ScriptTag = tag
        sr.Script = sc
        scripts.append(sr)
    sl = ot.ScriptList()
    sl.ScriptRecord = scripts
    sl.ScriptCount = len(scripts)
    gpos.ScriptList = sl

    tbl = newTable("GPOS")
    tbl.table = gpos
    font["GPOS"] = tbl
    if "GSUB" in font:
        del font["GSUB"]
    if "GDEF" in font:
        del font["GDEF"]
    for nid, val in ((1, "ShiftProbe"), (4, "ShiftProbe"), (6, "ShiftProbe")):
        font["name"].setName(val, nid, 3, 1, 0x409)
    font["post"].formatType = 2.0
    font["post"].glyphOrder = font.getGlyphOrder()
    font["post"].extraNames = []
    font["post"].mapping = {}
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    font.save(out)
    print(f"wrote {out}: XAdvance {SHIFT} on "
          + ", ".join(f"{m} ({f})" for m, f in MARKERS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
