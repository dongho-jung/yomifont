"""Okurigana alignment: split a (surface, reading) pair into ruby groups.

    食べる / たべる      ->  [(0, 1, "た")]                 べる is already kana
    取り戻す / とりもどす ->  [(0, 1, "と"), (2, 1, "もど")]
    東京 / とうきょう    ->  [(0, 2, "とうきょう")]
    お茶 / おちゃ        ->  [(1, 1, "ちゃ")]

The surface is cut into maximal runs of kana and of kanji.  Kana runs are
*anchors*: they must be found in the reading (allowing rendaku and gemination),
which pins down how much of the reading each kanji run owns.  A depth-first
search over "how many reading morae does this kanji run consume", trying the
shortest span first, resolves the rest; it is deterministic and needs no
per-entry judgement.

Deliberate design decision
--------------------------
A kanji run is emitted as ONE group (group ruby / グループルビ) rather than
being split per character.  Splitting 今日 into 今->きょ 日->う would be a
fabrication; the reading belongs to the lexical unit.  Optional mono-ruby
splitting is applied only where a high-confidence per-character split exists
(see split_mono_ruby).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .kana import (
    GEMINATION_SOURCES,
    SEMI_VOICED,
    UNVOICED,
    VOICED,
    is_kana,
    is_kanji,
    kata_to_hira,
)

# how much reading a single kanji character may plausibly own
MAX_MORAE_PER_KANJI = 8
# long institutional compounds legitimately need long group ruby
MAX_MORAE_PER_RUN = 28

VOWEL_OF = {}
for _row, _v in (
    ("あかさたなはまやらわがざだばぱゃゎ", "あ"),
    ("いきしちにひみりぎじぢびぴ", "い"),
    ("うくすつぬふむゆるぐずづぶぷゅっ", "う"),
    ("えけせてねへめれげぜでべぺ", "え"),
    ("おこそとのほもよろごぞどぼぽょ", "お"),
):
    for _c in _row:
        VOWEL_OF[_c] = _v


class AlignError(Exception):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


@dataclass(frozen=True, slots=True)
class RubyGroup:
    start: int   # index into surface
    length: int  # number of surface chars covered
    reading: str


def _kana_eq(surface_ch: str, reading_ch: str, first_in_run: bool, prev_reading: str) -> bool:
    """Can this surface kana be spelled as this reading kana?"""
    if surface_ch == reading_ch:
        return True
    # rendaku: the surface keeps the plain kana, the reading is voiced
    if VOICED.get(surface_ch) == reading_ch or SEMI_VOICED.get(surface_ch) == reading_ch:
        return True
    # the reverse (surface voiced, reading plain) shows up in variant spellings
    if UNVOICED.get(surface_ch) == reading_ch:
        return True
    # 促音便: reading has っ where the surface kana is a plain k/t row mora
    if reading_ch == "っ" and surface_ch in GEMINATION_SOURCES:
        return True
    if surface_ch == "っ" and reading_ch in GEMINATION_SOURCES:
        return True
    # 長音: ー in the surface spelled out as a vowel in the reading
    if surface_ch == "ー" and prev_reading and VOWEL_OF.get(prev_reading) == reading_ch:
        return True
    if reading_ch == "ー" and prev_reading and VOWEL_OF.get(prev_reading) == surface_ch:
        return True
    # ヶ / ヵ as a counter or place-name connective: 一ヶ月 -> いっかげつ
    if surface_ch in "ゖゕ" and reading_ch in "かがこ":
        return True
    return False


# Characters that are neither kana nor ruby-bearing bases.  Their presence in a
# surface makes the entry unusable.  (ー and 々 are NOT here: is_kana / is_kanji
# already classify them.)
_UNUSABLE = set("・=＝　 、。「」『』（）()［］【】〜~-−・／/,，.．!！?？:：;；'\"")


def _kind(ch: str) -> str:
    if is_kana(ch):
        return "kana"
    if is_kanji(ch):
        return "base"
    if ch in _UNUSABLE:
        return "other"
    # full-width digits, Latin letters and symbols used orthographically
    # (Ｘ線, １位, α線) carry readings just like kanji do
    return "base"


def _runs(surface: str) -> list[tuple[str, int, int]]:
    """[(kind, start, end)] where kind is 'base' (ruby-bearing) | 'kana' | 'other'."""
    out = []
    i = 0
    n = len(surface)
    while i < n:
        kind = _kind(surface[i])
        j = i + 1
        while j < n and _kind(surface[j]) == kind:
            j += 1
        out.append((kind, i, j))
        i = j
    return out


def align(surface: str, reading: str) -> list[RubyGroup]:
    """Raise AlignError on failure, otherwise return the ruby groups.

    `surface` is matched case-folded (katakana -> hiragana) against `reading`,
    but the returned offsets index the ORIGINAL surface.
    """
    runs = _runs(surface)
    surface = kata_to_hira(surface)
    if any(k == "other" for k, _, _ in runs):
        raise AlignError("non_japanese_char")
    if not any(k == "base" for k, _, _ in runs):
        raise AlignError("no_kanji")

    nr = len(reading)
    result: list[RubyGroup] = []

    def solve(ri: int, ridx: int) -> bool:
        if ri == len(runs):
            return ridx == nr
        kind, s, e = runs[ri]
        if kind == "kana":
            need = e - s
            if ridx + need > nr:
                return False
            for k in range(need):
                prev = reading[ridx + k - 1] if ridx + k > 0 else ""
                if not _kana_eq(surface[s + k], reading[ridx + k], k == 0, prev):
                    return False
            return solve(ri + 1, ridx + need)

        # ruby-bearing run: try the shortest plausible span first
        span = e - s
        hi = min(nr - ridx, MAX_MORAE_PER_RUN, MAX_MORAE_PER_KANJI * span)
        # a kanji run at the end of the word must consume everything left
        for take in range(1, hi + 1):
            if ri == len(runs) - 1 and ridx + take != nr:
                continue
            sub = reading[ridx : ridx + take]
            # a run may never start on a small kana or a prolongation mark
            if sub[0] in "ゃゅょぁぃぅぇぉっゎー":
                continue
            result.append(RubyGroup(s, span, sub))
            if solve(ri + 1, ridx + take):
                return True
            result.pop()
        return False

    if not solve(0, 0):
        raise AlignError("no_alignment")
    return result


def align_or_none(surface: str, reading: str) -> list[RubyGroup] | None:
    try:
        return align(surface, reading)
    except AlignError:
        return None


def whole_word_group(surface: str, reading: str) -> list[RubyGroup]:
    """Fallback: one ruby group spanning the entire surface."""
    return [RubyGroup(0, len(surface), reading)]
