"""Kana / kanji character classification and normalisation.

Everything here is pure table lookup and arithmetic -- no heuristics that need
tuning, so it can be trusted at 200k-entry scale.
"""
from __future__ import annotations

# --- Unicode blocks -------------------------------------------------------
HIRAGANA = (0x3041, 0x3096)
KATAKANA = (0x30A1, 0x30FA)
KATAKANA_PHONETIC_EXT = (0x31F0, 0x31FF)
KANA_PUNCT = (0x3099, 0x309C)  # combining/standalone dakuten
PROLONGED = 0x30FC  # ー
ITERATION_KANA = (0x309D, 0x309E)  # ゝゞ
ITERATION_KANA_KATA = (0x30FD, 0x30FE)  # ヽヾ
ITERATION_KANJI = 0x3005  # 々

CJK_BLOCKS = (
    (0x3400, 0x4DBF),  # Ext A
    (0x4E00, 0x9FFF),  # URO
    (0xF900, 0xFAFF),  # Compatibility Ideographs
    (0x20000, 0x2A6DF),  # Ext B
    (0x2A700, 0x2EBEF),  # Ext C-F
    (0x2F800, 0x2FA1F),  # Compatibility Supplement
)

KATAKANA_TO_HIRAGANA_DELTA = 0x30A1 - 0x3041  # 0x60


def is_hiragana(ch: str) -> bool:
    c = ord(ch)
    return HIRAGANA[0] <= c <= HIRAGANA[1] or ITERATION_KANA[0] <= c <= ITERATION_KANA[1]


def is_katakana(ch: str) -> bool:
    c = ord(ch)
    return (
        KATAKANA[0] <= c <= KATAKANA[1]
        or ITERATION_KANA_KATA[0] <= c <= ITERATION_KANA_KATA[1]
        or KATAKANA_PHONETIC_EXT[0] <= c <= KATAKANA_PHONETIC_EXT[1]
    )


def is_kana(ch: str) -> bool:
    return is_hiragana(ch) or is_katakana(ch) or ord(ch) == PROLONGED


def is_kanji(ch: str) -> bool:
    c = ord(ch)
    if c == ITERATION_KANJI:  # 々 behaves like a kanji for alignment purposes
        return True
    return any(lo <= c <= hi for lo, hi in CJK_BLOCKS)


def kata_to_hira(s: str) -> str:
    out = []
    for ch in s:
        c = ord(ch)
        if KATAKANA[0] <= c <= KATAKANA[1]:
            out.append(chr(c - KATAKANA_TO_HIRAGANA_DELTA))
        elif ITERATION_KANA_KATA[0] <= c <= ITERATION_KANA_KATA[1]:
            out.append(chr(c - KATAKANA_TO_HIRAGANA_DELTA))
        else:
            out.append(ch)
    return "".join(out)


# --- phonological variation used by okurigana alignment -------------------
# rendaku (sequential voicing): は -> ば/ぱ etc.
VOICED = {
    "か": "が", "き": "ぎ", "く": "ぐ", "け": "げ", "こ": "ご",
    "さ": "ざ", "し": "じ", "す": "ず", "せ": "ぜ", "そ": "ぞ",
    "た": "だ", "ち": "ぢ", "つ": "づ", "て": "で", "と": "ど",
    "は": "ば", "ひ": "び", "ふ": "ぶ", "へ": "べ", "ほ": "ぼ",
    "う": "ゔ",
}
SEMI_VOICED = {"は": "ぱ", "ひ": "ぴ", "ふ": "ぷ", "へ": "ぺ", "ほ": "ぽ"}

# reverse maps
UNVOICED = {v: k for k, v in VOICED.items()}
UNVOICED.update({v: k for k, v in SEMI_VOICED.items()})

SMALL_TO_LARGE = {
    "ぁ": "あ", "ぃ": "い", "ぅ": "う", "ぇ": "え", "ぉ": "お",
    "っ": "つ", "ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "ゎ": "わ",
}

# gemination: the final mora of an on-reading can become っ (促音便)
GEMINATION_SOURCES = set("きくちつ")

SMALL_KANA = set("ぁぃぅぇぉっゃゅょゎヵヶ")


def variants_of(mora: str) -> set[str]:
    """All kana a source mora may legitimately surface as inside a compound."""
    out = {mora}
    if mora in VOICED:
        out.add(VOICED[mora])
    if mora in SEMI_VOICED:
        out.add(SEMI_VOICED[mora])
    if mora in UNVOICED:
        out.add(UNVOICED[mora])
        base = UNVOICED[mora]
        if base in SEMI_VOICED:
            out.add(SEMI_VOICED[base])
        if base in VOICED:
            out.add(VOICED[base])
    if mora in GEMINATION_SOURCES:
        out.add("っ")
    return out


def normalize_reading(reb: str) -> str:
    """Readings are stored as hiragana; katakana readings are folded."""
    return kata_to_hira(reb)


def strip_non_reading(s: str) -> str:
    """Remove characters JMdict sometimes leaves inside readings (middots etc.)."""
    return "".join(ch for ch in s if ch not in "・=＝ 　")
