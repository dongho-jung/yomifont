#!/usr/bin/env python3
"""Build the font for raster_probe.html.

Is an engine failing to *shape* the ruby, or failing to *draw* it?

Builds a font with no GSUB at all, where ordinary Latin letters are mapped
straight to ruby-style composites of increasing exoticism.  Whatever Chrome
draws or does not draw is then purely a rasterisation question.

    A  plain kana, no composite            control
    B  Phase 1 shape:  composite(kana, scale .5), offset y=900, one level
    C  Phase 2 shape:  composite(composite(kana, scale .5)), offset y=940
    D  as C but y=900
    E  as C but positive x offset only
    F  as C with a large negative x offset
"""
from __future__ import annotations

import sys

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphComponent
from fontTools import subset

SRC = "data/raw/NotoSansJP-Regular.ttf"
KANA = "と"


def comp(glyf, hmtx, name, ref, x, y, scale):
    g = Glyph()
    g.numberOfContours = -1
    c = GlyphComponent()
    c.glyphName = ref
    c.x, c.y = int(x), int(y)
    c.flags = 0
    c.transform = [[scale, 0], [0, scale]]
    g.components = [c]
    glyf.glyphs[name] = g
    hmtx.metrics[name] = (0, 0)
    return name


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "dist/RasterTest.ttf"
    font = TTFont(SRC)
    opts = subset.Options()
    opts.layout_features = []
    opts.glyph_names = True
    opts.notdef_outline = True
    ss = subset.Subsetter(options=opts)
    ss.populate(text=KANA + "ABCDEF東京")
    ss.subset(font)

    glyf, hmtx = font["glyf"], font["hmtx"]
    cmap = font.getBestCmap()
    kana = cmap[ord(KANA)]

    order = list(font.getGlyphOrder())
    new = []
    # one-level, Phase 1 shape
    new.append(comp(glyf, hmtx, "t.B", kana, 0, 900, 0.5))
    # two-level, Phase 2 shape
    comp(glyf, hmtx, "t.half", kana, 0, 0, 0.5)
    new.append("t.half")
    new.append(comp(glyf, hmtx, "t.C", "t.half", 0, 940, 1.0))
    new.append(comp(glyf, hmtx, "t.D", "t.half", 0, 900, 1.0))
    new.append(comp(glyf, hmtx, "t.E", "t.half", 250, 940, 1.0))
    new.append(comp(glyf, hmtx, "t.F", "t.half", -6900, 940, 1.0))
    font.setGlyphOrder(order + new)
    font["maxp"].numGlyphs = len(font.getGlyphOrder())
    for n in new:
        glyf.glyphs[n].recalcBounds(glyf)
        font["hmtx"].metrics[n] = (0, glyf.glyphs[n].xMin)
        if "vmtx" in font:
            font["vmtx"].metrics[n] = (0, 0)

    # A is the plain kana; B..F are the composites, straight through cmap
    mapping = {"A": kana, "B": "t.B", "C": "t.C", "D": "t.D", "E": "t.E", "F": "t.F"}
    for table in font["cmap"].tables:
        for ch, gname in mapping.items():
            table.cmap[ord(ch)] = gname

    for t in ("GSUB", "GPOS", "GDEF"):
        if t in font:
            del font[t]
    font["hhea"].ascent = 1400
    font["hhea"].descent = -288
    os2 = font["OS/2"]
    os2.usWinAscent, os2.usWinDescent = 1400, 288
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = 1400, -288, 0
    os2.fsSelection |= 1 << 7
    font["head"].yMax = max(font["head"].yMax, 1400)
    for nid, val in ((1, "RasterTest"), (4, "RasterTest"), (6, "RasterTest")):
        font["name"].setName(val, nid, 3, 1, 0x409)
    font["post"].formatType = 2.0
    font["post"].glyphOrder = font.getGlyphOrder()
    font["post"].extraNames = []
    font["post"].mapping = {}
    font.save(out)
    print(f"wrote {out}")
    for n in ["t.B", "t.C", "t.D", "t.E", "t.F"]:
        g = glyf[n]
        print(f"  {n}: bbox=({g.xMin},{g.yMin},{g.xMax},{g.yMax}) lsb={hmtx[n][1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
