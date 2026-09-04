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

# --- the Aozora form, which also works where the text is split into runs ----
# Blink itemises before shaping and never puts a Han base and a Kana reading in
# one buffer, so the rule above -- which needs the whole expression at once --
# gets nothing on a kanji base, the case the feature exists for.
#
# Splitting it into two rules, one per run, needs no information to cross the
# boundary at all:
#
#     〇月《   one run: the marker, the base, the opener
#     ライト》 another: the reading and the closer
#
# Three characters make that work, each chosen from measurement rather than
# from the Unicode properties (tests/integration/itemize_probe.html):
#
#   〇  U+3007, Script=Han. A preceding kana run cannot absorb it, which is
#       exactly what goes wrong with ｜: ｜ is Script=Common and joins whatever
#       is in front of it, so after a particle the first rule loses its marker
#       and the expression renders half-done. 〇 measured SPLIT after both
#       hiragana and katakana, and SAME_RUN before Han. ◯, ※, 〓 and 〆 all
#       failed the same test. It is also easy to type: まる converts to it.
#   《》 U+300A/U+300B, the Aozora Bunko ruby delimiters. They remove the need
#       for a trailing marker: the second rule is `KANA+ 》`, and 《かな》 is
#       rare in ordinary prose *and* already means ruby by convention, where
#       `KANA+ ）` would have swallowed 私（わたし）.
#
# The marker is required, unlike in Aozora. Aozora can infer the base from the
# preceding kanji run because a human reads the whole line; the first run
# cannot see whether a reading follows the 《, so an inferring rule would hide
# the bracket of any 漢字《…》 in ordinary prose -- 小説《ノルウェイの森》 came
# out as 小説ノルウェイの森》. The marker is what makes the intent visible
# inside the first run.
#
# In Blink the marker only reaches the base when both are ideographs, since 〇
# is Han and a kana base starts its own run. A kana base there keeps working
# with the ｜BASE（RUBY） form, which is a single run in Blink anyway.
MARK = "〇"
AOZORA_OPEN = "《"
AOZORA_CLOSE = "》"

DELIMITERS = START + OPEN + CLOSE + MARK + AOZORA_OPEN + AOZORA_CLOSE

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


# --- the split form's layout ----------------------------------------------
# Ruby is right-aligned to the end of the base, at a fixed pitch, in one size.
#
# Not a preference -- it is what the second run can compute on its own. It
# starts exactly where the base ends (the delimiters are zero-advance), and it
# knows how many kana it has, so growing leftward from its own origin needs
# nothing from the first run. Centring would need the base width. The first run
# *can* move the second, and Chrome honours a negative XAdvance across the run
# boundary (tests/integration/shift_probe.html), but it buys nothing: whatever
# the first run subtracts, something has to add back to keep the line correct,
# and only the first run knows how much.
#
# So the split form trades 均等割り付け and size stepping for working at all
# where the text is itemised. Engines that hand over the whole expression still
# get the single-run rules, which come first and consume the span.
SPLIT_SIZE = 0.50
SPLIT_PITCH = int(SPLIT_SIZE * EM)


def split_offsets(n: int) -> list[int]:
    """Left edge of each of `n` ruby kana, right-aligned to the base end."""
    return [-(n - i) * SPLIT_PITCH for i in range(n)]


def split_cells(limits: Limits = DEFAULT_LIMITS) -> set[tuple[float, int]]:
    return {(SPLIT_SIZE, x) for n in range(1, limits.ruby + 1)
            for x in split_offsets(n)}


def split_inventory(alpha: str,
                    limits: Limits = DEFAULT_LIMITS) -> set[tuple[str, float, int]]:
    cells = split_cells(limits)
    return {(ch, s, x) for ch in alpha for s, x in cells}


def variants_for(cells: list[tuple[float, int]], reading_len: int) -> list[str]:
    """Debug helper: the glyph names one (B, N) expression substitutes to."""
    return [variant_name("あ", size, x) for size, x in cells[:reading_len]]
