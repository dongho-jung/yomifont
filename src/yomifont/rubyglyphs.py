"""Reusable ruby-kana glyph inventory.

The whole point of the architecture is that a lexical rule set of any size is
served by a *small, shared* set of ruby glyphs.  A ruby kana needs to appear at
many different horizontal offsets, so the inventory is indexed by

    (kana character, t)      where  x_offset = QUARTER_EM * t

and t is derived from the geometry of the word the ruby sits on:

    x_i = group_start*EM + (M*EM - N*RUBY_ADV)/2 + i*RUBY_ADV
        = QUARTER_EM * (4*group_start + 2*M - N + 2*i)

with M = base characters spanned, N = kana in the reading, i = index of this
kana.  So t = 4*group_start + 2*M - N + 2*i, an integer.

Each variant is a *nested* TrueType composite:

    rk.<cp>          composite(base kana, scale=RUBY_SCALE, offset 0/0)
    r.<cp>.t<t>      composite(rk.<cp>,   scale=1,           offset 250t/RUBY_Y)

The nesting is deliberate.  A single composite that both scales and offsets is
ambiguous: Apple and Microsoft rasterizers disagree about whether the offset is
applied before or after the scale (SCALED_COMPONENT_OFFSET vs
UNSCALED_COMPONENT_OFFSET).  With the scale at depth 2 carrying a zero offset
and the offset at depth 1 carrying no scale, both conventions give the same
result.

Positioning is baked into the outline rather than applied with GPOS, so the
font needs no GPOS table at all -- one less thing for an engine to skip.
"""
from __future__ import annotations

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphComponent

EM = 1000
QUARTER_EM = EM // 4
RUBY_SCALE = 0.5
RUBY_ADV = int(EM * RUBY_SCALE)


def ruby_t(group_start: int, span: int, n_kana: int, i: int) -> int:
    """Horizontal slot index of the i-th ruby kana, in quarter-em units."""
    return 4 * group_start + 2 * span - n_kana + 2 * i


def half_name(ch: str) -> str:
    return "rk.%04X" % ord(ch)


def variant_name(ch: str, t: int) -> str:
    return "r.%04X.t%s" % (ord(ch), ("m%d" % -t) if t < 0 else str(t))


def collect(needed: set[tuple[str, int]]) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for ch, t in needed:
        out.setdefault(ch, set()).add(t)
    return out


def add_ruby_glyphs(
    font: TTFont,
    needed: dict[str, set[int]],
    ruby_y: int,
    scale: float = RUBY_SCALE,
) -> list[str]:
    """Create the ruby glyph inventory in `font`.  Returns the new glyph names."""
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    # Noto Sans JP ships vertical metrics; every glyph in the order must have a
    # vmtx entry or the table fails to compile.
    vmtx = font["vmtx"] if "vmtx" in font else None
    cmap = font.getBestCmap()
    order = list(font.getGlyphOrder())
    new: list[str] = []

    for ch in sorted(needed):
        src = cmap.get(ord(ch))
        if src is None:
            raise KeyError(f"base font has no glyph for ruby kana {ch!r} U+{ord(ch):04X}")
        hn = half_name(ch)
        if hn not in glyf.glyphs:
            g = Glyph()
            g.numberOfContours = -1
            c = GlyphComponent()
            c.glyphName = src
            c.x = c.y = 0
            c.flags = 0
            c.transform = [[scale, 0], [0, scale]]
            g.components = [c]
            glyf.glyphs[hn] = g
            hmtx.metrics[hn] = (0, 0)
            new.append(hn)

        for t in sorted(needed[ch]):
            vn = variant_name(ch, t)
            if vn in glyf.glyphs:
                continue
            g = Glyph()
            g.numberOfContours = -1
            c = GlyphComponent()
            c.glyphName = hn
            c.x = QUARTER_EM * t
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
    # lsb at 0 silently throws the whole horizontal offset away (verified: the
    # ruby collapses into a stack over the first character).  Setting lsb =
    # xMin makes that translation a no-op in every engine.
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
