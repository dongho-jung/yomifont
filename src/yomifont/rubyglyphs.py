"""Reusable ruby-kana glyph inventory.

A lexical rule set of any size is served by a small shared set of ruby glyphs,
because a ruby glyph's identity is only

    (kana character, size, x offset on the QUANTUM grid)

and never the word it appears in.  Phase 1 used a quarter-em grid and a single
size, which kept the inventory tiny but made real typography impossible; Phase
2 uses a twentieth-em grid and three sizes, which is what lets
yomifont.layout distribute readings properly.  The inventory still saturates,
just at a larger number.

Each variant is a *nested* TrueType composite:

    rk.<cp>.<size>   composite(base kana, scale=size, offset 0/0)
    r.<cp>.<size>.<x> composite(rk.<cp>.<size>, scale=1, offset x/RUBY_Y)

The nesting is deliberate.  A single composite that both scales and offsets is
ambiguous: Apple and Microsoft rasterizers disagree about whether the offset is
applied before or after the scale (SCALED_COMPONENT_OFFSET vs
UNSCALED_COMPONENT_OFFSET).  With the scale at depth 2 carrying a zero offset
and the offset at depth 1 carrying no scale, both conventions agree.

Positioning is baked into the outline rather than applied with GPOS, so the
font needs no GPOS table at all.
"""
from __future__ import annotations

import os

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphComponent

from .layout import EM, QUANTUM

# Vertical placement of the ruby baseline. Kanji ink in Noto Sans JP tops out
# near y=843; 940 clears it with a gap that reads as deliberate rather than
# stacked, and keeps 0.5 em ruby under y=1360.
RUBY_Y = 940

# Ruby outlines are taken from a HEAVIER instance of the variable base font.
# Scaling a Regular kana to half size scales its stroke weight too, and small
# text set that way reads noticeably lighter than the body it sits above --
# the optical-size compensation a real type family would build in. wght 500
# against a 400 body restores the apparent weight without changing the shapes.
RUBY_SOURCE_WEIGHT = 500


def half_name(ch: str, size: float) -> str:
    return "rk.%04X.%02d" % (ord(ch), round(size * 100))


def variant_name(ch: str, size: float, x: int) -> str:
    slot = x // QUANTUM
    return "r.%04X.%02d.%s" % (ord(ch), round(size * 100),
                               ("m%d" % -slot) if slot < 0 else str(slot))


def _import_ruby_outlines(font: TTFont, kana: set[str], source_path: str) -> dict[str, str]:
    """Copy the kana outlines from a heavier instance in as new glyphs.

    Returns kana char -> glyph name in `font`.  Falls back to the font's own
    kana when no source is available, so the build never hard-depends on it.
    """
    cmap = font.getBestCmap()
    if not source_path or not os.path.exists(source_path):
        return {ch: cmap[ord(ch)] for ch in kana if ord(ch) in cmap}

    src = TTFont(source_path, lazy=True)
    src_cmap = src.getBestCmap()
    src_gs = src.getGlyphSet()
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    vmtx = font["vmtx"] if "vmtx" in font else None
    added: list[str] = []
    out: dict[str, str] = {}
    for ch in sorted(kana):
        cp = ord(ch)
        if cp not in src_cmap:
            if cp in cmap:
                out[ch] = cmap[cp]
            continue
        name = "rsrc.%04X" % cp
        if name not in glyf.glyphs:
            pen = TTGlyphPen(src_gs)
            src_gs[src_cmap[cp]].draw(pen)
            glyf.glyphs[name] = pen.glyph()
            hmtx.metrics[name] = (0, 0)
            if vmtx is not None:
                vmtx.metrics[name] = (0, 0)
            added.append(name)
        out[ch] = name
    if added:
        font.setGlyphOrder(list(font.getGlyphOrder()) + added)
        font["maxp"].numGlyphs = len(font.getGlyphOrder())
        for name in added:
            glyf.glyphs[name].recalcBounds(glyf)
            hmtx.metrics[name] = (0, glyf.glyphs[name].xMin)
    return out


def add_ruby_glyphs(
    font: TTFont,
    needed: set[tuple[str, float, int]],
    ruby_y: int = RUBY_Y,
    source_path: str = "",
) -> list[str]:
    """Create every (kana, size, x) variant in `needed`. Returns new names."""
    src_for = _import_ruby_outlines(font, {k for k, _, _ in needed}, source_path)
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    vmtx = font["vmtx"] if "vmtx" in font else None
    cmap = font.getBestCmap()
    order = list(font.getGlyphOrder())
    new: list[str] = []

    sizes_by_kana: dict[tuple[str, float], list[int]] = {}
    for ch, size, x in needed:
        sizes_by_kana.setdefault((ch, size), []).append(x)

    for (ch, size), xs in sorted(sizes_by_kana.items()):
        src = src_for.get(ch) or cmap.get(ord(ch))
        if src is None:
            raise KeyError(f"base font has no glyph for ruby kana {ch!r}")
        hn = half_name(ch, size)
        if hn not in glyf.glyphs:
            g = Glyph()
            g.numberOfContours = -1
            c = GlyphComponent()
            c.glyphName = src
            c.x = c.y = 0
            c.flags = 0
            c.transform = [[size, 0], [0, size]]
            g.components = [c]
            glyf.glyphs[hn] = g
            hmtx.metrics[hn] = (0, 0)
            new.append(hn)
        for x in sorted(set(xs)):
            vn = variant_name(ch, size, x)
            if vn in glyf.glyphs:
                continue
            g = Glyph()
            g.numberOfContours = -1
            c = GlyphComponent()
            c.glyphName = hn
            c.x = int(x)
            c.y = ruby_y
            c.flags = 0
            c.transform = [[1, 0], [0, 1]]
            g.components = [c]
            glyf.glyphs[vn] = g
            hmtx.metrics[vn] = (0, 0)
            new.append(vn)

    font.setGlyphOrder(order + new)
    font["maxp"].numGlyphs = len(font.getGlyphOrder())

    # A TrueType rasterizer re-origins every outline by (lsb - xMin): FreeType's
    # TT_Process_Simple_Glyph translates by -pp1.x where pp1.x = xMin - lsb.
    # Our ruby glyphs carry their placement *inside* the outline, so leaving
    # lsb at 0 silently throws the whole horizontal offset away.
    for name in new:
        glyf.glyphs[name].recalcBounds(glyf)
        hmtx.metrics[name] = (0, glyf.glyphs[name].xMin)
        if vmtx is not None:
            vmtx.metrics[name] = (0, 0)
    return new


def add_blank_glyph(font: TTFont, name: str = "ruby.blank") -> str:
    """A zero-advance empty glyph, used to suppress ruby in vertical mode."""
    glyf = font["glyf"]
    if name in glyf.glyphs:
        return name
    g = Glyph()
    g.numberOfContours = 0
    g.xMin = g.yMin = g.xMax = g.yMax = 0
    glyf.glyphs[name] = g
    font["hmtx"].metrics[name] = (0, 0)
    if "vmtx" in font:
        font["vmtx"].metrics[name] = (0, 0)
    font.setGlyphOrder(list(font.getGlyphOrder()) + [name])
    font["maxp"].numGlyphs = len(font.getGlyphOrder())
    return name
