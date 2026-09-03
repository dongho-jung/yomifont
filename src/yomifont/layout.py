"""Ruby layout: where each kana of a reading actually goes.

Phase 1 used one formula -- pack the kana at a fixed half-em pitch and centre
them -- which is mechanically correct and typographically poor.  It produced
ruby that ran together across adjacent words (東京都新宿区 read as one
undifferentiated とうきょうとしんじゅくく), left long readings colliding with
their neighbours, and squeezed short readings into a tight clump floating in
the middle of a wide base.

This module implements the conventions from JIS X 4051 / the W3C Japanese
Layout Requirements that a font can actually honour:

* **均等割り付け (even distribution).**  When the ruby is narrower than its
  base, JLREQ distributes it so the space at each end is half the space
  between ruby characters.  That is what makes 図書館 / としょかん look set
  rather than stacked, and it produces end insets for free, which is what
  keeps neighbouring groups apart.

* **Overhang, bounded.**  When the ruby is wider than its base it may hang
  over adjacent characters -- real books do this constantly for 東京 /
  とうきょう -- but only up to a limit, because the font cannot see whether
  the neighbour has ruby of its own.

* **Tracking before size.**  Past the overhang budget, tighten the pitch
  before shrinking the glyphs; only when tracking is exhausted does the ruby
  step down a size.  Shrinking is the last resort, not the first.

Everything returns integer offsets on a QUANTUM grid, because the offset is
what identifies a reusable ruby glyph.  A finer grid buys better typography at
the cost of more glyphs, and the grid is the knob that trades them off.
"""
from __future__ import annotations

from dataclasses import dataclass

EM = 1000

# Placement grid.  Phase 1 used 250 (a quarter em), which forced every ruby
# kana onto a coarse lattice and made real distribution impossible.  50 is a
# twentieth of an em: fine enough that distribution reads as even, coarse
# enough that the glyph inventory still saturates.
QUANTUM = 50

# Ruby sizes, largest first.  0.5 em is the conventional furigana size; the
# smaller steps are only used when a reading cannot otherwise be fitted.
RUBY_SIZES = (0.50, 0.44, 0.38)

# Fraction of the ruby advance that tracking may be tightened by before the
# next size down is tried.  Kana ink is narrower than its em box, so a little
# negative tracking is invisible.
MIN_TRACKING = 0.86

# How far ruby may hang past the edge of its base span, in em units. Half a
# ruby character. Two adjacent groups can therefore approach each other but a
# group is never wider than its base plus one ruby character.
MAX_OVERHANG = 0.25 * EM

# Minimum air left at each end of the base span when the ruby does fit inside
# it, so adjacent groups stay visibly separate.
MIN_END_INSET = 0.04 * EM


@dataclass(frozen=True, slots=True)
class Placed:
    """One ruby kana: which glyph size, and where its origin sits."""
    kana: str
    size: float
    x: int          # left edge of the kana's box, in font units from span start


# Which is preferred when a reading is too wide for its base: keeping the
# conventional 0.5 em ruby and letting it hang over the neighbours ("overhang",
# what books do), or stepping the size down so the group always stays inside
# its own base span ("contain", which guarantees adjacent groups never touch).
# A font cannot see whether the neighbour has ruby of its own, which is the
# argument for "contain"; see docs/typography.md for the rendered comparison.
POLICY_CONTAIN = "contain"
POLICY_OVERHANG = "overhang"
DEFAULT_POLICY = POLICY_CONTAIN


def _distribute(reading, size, base_x, base_w, n):
    """均等割り付け: end gaps half the inter-character gap."""
    adv = size * EM
    gap = (base_w - n * adv) / n
    start = gap / 2
    return [Placed(reading[i], size, _q(base_x + start + i * (adv + gap)))
            for i in range(n)]


def _track(reading, size, base_x, left, width, n):
    """Even pitch across `width`, each kana centred in its slot."""
    adv = size * EM
    pitch = width / n
    start = left + (pitch - adv) / 2
    return [Placed(reading[i], size, _q(base_x + start + i * pitch))
            for i in range(n)]


def layout_group(span_start: int, span_len: int, reading: str,
                 policy: str = DEFAULT_POLICY) -> list[Placed]:
    """Place `reading` over `span_len` full-width characters at `span_start`.

    Offsets are absolute from the start of the whole matched word, because all
    of a word's ruby is emitted from one substitution.
    """
    n = len(reading)
    if n == 0:
        return []
    base_x = span_start * EM
    base_w = span_len * EM
    inner = base_w - 2 * MIN_END_INSET
    outer = base_w + 2 * MAX_OVERHANG

    def fits_inside(size):
        adv = size * EM
        natural = n * adv
        if natural <= inner:
            return _distribute(reading, size, base_x, base_w, n)
        # A hair too wide: tighten the pitch rather than overhang. This is the
        # 東京都 case -- six kana over three characters is exactly 3.0 em, and
        # without this it butts straight against the next word's ruby.
        if inner / n >= adv * MIN_TRACKING:
            return _track(reading, size, base_x, MIN_END_INSET, inner, n)
        return None

    def fits_with_overhang(size):
        adv = size * EM
        natural = n * adv
        if natural <= outer:
            return _track(reading, size, base_x, (base_w - natural) / 2, natural, n)
        if outer / n >= adv * MIN_TRACKING:
            return _track(reading, size, base_x, -MAX_OVERHANG, outer, n)
        return None

    order = ([fits_inside, fits_with_overhang] if policy == POLICY_CONTAIN
             else [fits_with_overhang, fits_inside])
    for attempt in order:
        for size in RUBY_SIZES:
            placed = attempt(size)
            if placed is not None:
                return placed

    # Nothing fits at any size: a long reading on a single kanji
    # (承る -> うけたまわ). Smallest size, spread across the overhang box.
    return _track(reading, RUBY_SIZES[-1], base_x, -MAX_OVERHANG, outer, n)


def _q(x: float) -> int:
    return int(round(x / QUANTUM)) * QUANTUM


def layout_word(groups, policy: str = DEFAULT_POLICY) -> list[Placed]:
    """All ruby for one rule, in emission order."""
    out: list[Placed] = []
    for start, length, reading in groups:
        out.extend(layout_group(start, length, reading, policy))
    return out


def describe(groups, policy: str = DEFAULT_POLICY) -> str:
    """Debug view of a word's ruby placement."""
    return "  ".join(f"{p.kana}@{p.x}/{p.size}" for p in layout_word(groups, policy))
