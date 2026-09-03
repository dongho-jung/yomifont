"""Explicit Ruby: readings the user writes into the text, resolved by GSUB.

    ｜月（ライト）        ｜ U+FF5C   （ U+FF08   ） U+FF09
    |月(ライト)           | U+007C   ( U+0028   ) U+0029

Both syntaxes compile to the same rules, because a Coverage table is a set: the
fullwidth and ASCII delimiters simply sit in the same three sets.

Why this is not a second renderer
---------------------------------
One ChainContextSubst rule matches a whole

    START BASE{B} OPEN RUBY{N} CLOSE

expression and carries one SingleSubst record per position.  Every record is a
1:1 substitution, so the glyph count never changes and the sequence indices
stay valid -- which is the constraint that `gsub` documents for the automatic
side.  The records do four things:

    START, OPEN, CLOSE  ->  a zero-advance blank            (markup disappears)
    each BASE glyph     ->  a protected duplicate           (automatic ruby off)
    each RUBY glyph     ->  r.<cp>.<size>.<slot>            (the same inventory
                                                             the automatic side
                                                             uses, same layout)

Nothing in the rule mentions a particular word.  A rule is chosen by the
*shape* of the expression -- how many base characters, how many ruby characters
-- so a base string the font has never seen gets ruby as long as its length and
its ruby characters are in range.  That is the difference between this and a
dictionary.

Where the ruby actually lands
-----------------------------
The delimiters are zero-advance and the ruby glyphs are zero-advance, so the
pen sits at exactly B em when the ruby characters are reached.  Ruby kana i
therefore needs

    offset = layout.layout_group(0, B, reading)[i].x  -  B * EM

which depends only on (B, N, i) and never on which kana it is.  That is what
bounds the inventory: |alphabet| x |distinct (size, offset)|, not |words|.

The cost of a longer base
-------------------------
Those offsets have to span the whole base span, so the number of distinct
offsets grows with the base limit at roughly 20 slots per base character, and
the glyph count is that times the alphabet.  With a 183-character kana
alphabet on the automatic side's 1/20 em grid, base<=6 is all that fits under
the 65,535-glyph TrueType ceiling.  `GRID` coarsens the placement lattice for
explicit ruby only; docs/explicit-ruby.md has the measured curve and the
rendered comparison behind the default.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .layout import DEFAULT_POLICY, EM, QUANTUM, layout_group
from .rubyglyphs import variant_name

# --- syntax ---------------------------------------------------------------
START = "｜|"    # U+FF5C FULLWIDTH VERTICAL LINE, U+007C VERTICAL LINE
OPEN = "（("     # U+FF08 FULLWIDTH LEFT PARENTHESIS, U+0028 LEFT PARENTHESIS
CLOSE = "）)"    # U+FF09 FULLWIDTH RIGHT PARENTHESIS, U+0029 RIGHT PARENTHESIS
DELIMITERS = START + OPEN + CLOSE

# --- ruby alphabet --------------------------------------------------------
# Every character that may appear inside （...）.  Each one costs
# |distinct (size, offset)| glyphs, so this is the expensive axis and it is
# kept to the kana repertoire plus the marks that occur inside real furigana.
HIRAGANA = "".join(chr(c) for c in range(0x3041, 0x3097))   # ぁ..ゖ
KATAKANA = "".join(chr(c) for c in range(0x30A1, 0x30FB))   # ァ..ヺ
KANA_MARKS = "ー・ゝゞヽヾ〜"          # 長音符, 中点, iteration marks
ALPHABET = HIRAGANA + KATAKANA + KANA_MARKS

# Latin and digits are supported as *base* characters for free -- they are
# ordinary glyphs and need no new inventory -- so ｜AI（エーアイ）and
# ｜2026（にせんにじゅうろく）work without this.  Putting them in the *ruby*
# alphabet costs another |pairs| glyphs each, which is the measurement in
# docs/explicit-ruby.md; off by default.
LATIN_RUBY = ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
              "0123456789")


def alphabet(latin: bool = False) -> str:
    return ALPHABET + (LATIN_RUBY if latin else "")


# --- limits ---------------------------------------------------------------
# Placement lattice for explicit ruby, in font units.  Must be a multiple of
# layout.QUANTUM so the offsets stay on the shared grid and the glyph names
# stay compatible with the automatic inventory.
GRID = 100


@dataclass(frozen=True, slots=True)
class Limits:
    base: int = 8
    ruby: int = 16

    def __post_init__(self):
        if self.base < 1 or self.ruby < 1:
            raise ValueError("limits must be >= 1")


DEFAULT_LIMITS = Limits()


def _snap(x: int, grid: int) -> int:
    """Round to the placement lattice, halves always upward.

    Not `round()`: it rounds halves to even, and because every layout offset is
    already a multiple of QUANTUM, *every* offset sits exactly on a half when
    the grid is 2*QUANTUM.  Banker's rounding then alternates direction along a
    reading and turns an evenly spaced group into an uneven one -- ライト over
    月 came out at 400/600 unit steps instead of 500/500.  Rounding halves one
    consistent way keeps an arithmetic progression arithmetic whenever the
    pitch is a multiple of the grid.
    """
    return math.floor(x / grid + 0.5) * grid


def placements(limits: Limits = DEFAULT_LIMITS, policy: str = DEFAULT_POLICY,
               grid: int = GRID) -> dict[tuple[int, int], list[tuple[float, int]]]:
    """(B, N) -> [(size, offset) for each ruby character].

    `offset` is relative to the pen position after the base span, which is
    where every ruby glyph in the expression is emitted.
    """
    if grid % QUANTUM:
        raise ValueError(f"grid {grid} must be a multiple of QUANTUM {QUANTUM}")
    dummy = "あ" * limits.ruby
    out: dict[tuple[int, int], list[tuple[float, int]]] = {}
    for b in range(1, limits.base + 1):
        for n in range(1, limits.ruby + 1):
            out[(b, n)] = [(p.size, _snap(p.x - b * EM, grid))
                           for p in layout_group(0, b, dummy[:n], policy)]
    return out


def offsets(limits: Limits = DEFAULT_LIMITS, policy: str = DEFAULT_POLICY,
            grid: int = GRID) -> set[tuple[float, int]]:
    """The distinct (size, offset) pairs a build has to carry."""
    return {cell for cells in placements(limits, policy, grid).values()
            for cell in cells}


def inventory(alpha: str, limits: Limits = DEFAULT_LIMITS,
              policy: str = DEFAULT_POLICY,
              grid: int = GRID) -> set[tuple[str, float, int]]:
    """(kana, size, x) triples for `rubyglyphs.add_ruby_glyphs`."""
    cells = offsets(limits, policy, grid)
    return {(ch, size, x) for ch in alpha for size, x in cells}


def cost(alpha: str, limits: Limits = DEFAULT_LIMITS,
         policy: str = DEFAULT_POLICY, grid: int = GRID) -> dict:
    """What a given configuration costs, for the scaling benchmark."""
    pl = placements(limits, policy, grid)
    off = {c for cells in pl.values() for c in cells}
    return {
        "base_max": limits.base,
        "ruby_max": limits.ruby,
        "grid": grid,
        "alphabet": len(alpha),
        "expressions": len(pl),
        "offset_pairs": len(off),
        "ruby_glyphs": len(off) * len(alpha),
        "records": sum(len(c) + 3 + b for (b, _), c in pl.items()),
    }


def variants_for(cells: list[tuple[float, int]], reading_len: int) -> list[str]:
    """Debug helper: the glyph names one (B, N) expression substitutes to."""
    return [variant_name("あ", size, x) for size, x in cells[:reading_len]]
