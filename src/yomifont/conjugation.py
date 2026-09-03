"""Conjugation handling.

Real Japanese text is full of inflected verbs, but a font rule keyed on the
dictionary form 書く never fires on 書きました.  Rather than exploding every
inflected form into its own rule (~20x the rule count), we exploit the fact
that **the reading of the kanji does not change under inflection**:

    書く 書かない 書きます 書いた 書けば 書こう   ->  書 is always か

So one rule per (stem, first-okurigana-character) covers every inflection:

    v5k 書く   stem 書   ->  書か 書き 書く 書け 書こ 書い     6 rules
    v1  食べる stem 食べ ->  食べ                              1 rule
    v1  見る   stem 見   ->  見る 見た 見て ...               11 rules

The rule *input* stops at the first inflecting character, so whatever follows
(ました / なかった / られる ...) is plain kana and needs no ruby.

Irregular verbs whose kanji reading DOES change (来る -> く/き/こ) get an
explicit form table instead.
"""
from __future__ import annotations

# Characters that can directly follow the stem, per JMdict POS code.
# These are the 未然/連用/終止/仮定/命令/音便 columns of the godan table plus
# the sound-change (音便) form used by the past/te forms.
GODAN_ENDINGS = {
    "v5k": "かきくけこい",     # 書く -> 書いた
    "v5k-s": "かきくけこっ",   # 行く -> 行った  (special class, no い-onbin)
    "v5g": "がぎぐげごい",     # 泳ぐ -> 泳いだ
    "v5s": "さしすせそ",
    "v5t": "たちつてとっ",
    "v5n": "なにぬねのん",
    "v5b": "ばびぶべぼん",
    "v5m": "まみむめもん",
    "v5r": "らりるれろっ",
    "v5r-i": "らりるれろ",     # ある
    "v5u": "わいうえおっ",
    "v5u-s": "わいうえおう",   # 問う -> 問うた
    "v5aru": "らりるれろっ",
    "v4r": "らりるれろっ",
    "v4k": "かきくけこい",
    "v4s": "さしすせそ",
    "v4t": "たちつてとっ",
    "v4h": "はひふへほう",
    "v4m": "まみむめもん",
    "v4g": "がぎぐげごい",
    "v4b": "ばびぶべぼん",
    "v4n": "なにぬねのん",
}

# Ichidan and adjective stems are formed by dropping the final kana of the
# dictionary form.  When the resulting stem still ends in kana it is already
# unambiguous and needs no lookahead character; when it ends in a kanji we
# append one character from this set.
# 見る 見た 見て 見ない 見ます 見れば 見よう 見られる 見させる 見ず 見ろ
# Deliberately excludes い / き / し: an ichidan verb has no such form, and
# including them made 着る collide with 着く (着い -> きい instead of つい).
ICHIDAN_NEXT = "るたてなまれよらろずさせ"
ADJ_I_NEXT = "いくかけさすげみ"          # 高い 高く 高かった 高ければ 高さ ...

# A noun tagged `vs` forms a verb with する.  Emitting stem rules for it is not
# about coverage -- 勉強 alone already matches inside 勉強しました -- but about
# *precedence*: without 外出し, the rare noun 外出し (そとだし) is a longer rule
# and wins longest-match over 外出 (がいしゅつ) + し.
SURU_NEXT = "しすさせ"

DROP_FINAL = {"v1", "v1-s", "vk", "vz", "vs-s", "vs-i", "adj-i", "adj-ix"}

VERB_POS = set(GODAN_ENDINGS) | DROP_FINAL

# Irregular verbs whose *kanji reading* changes across the paradigm.
# surface-suffix -> reading of the kanji part.
IRREGULAR: dict[str, list[tuple[str, str]]] = {
    # 来る (くる)
    "来": [
        ("来る", "く"), ("来ます", "き"), ("来ました", "き"), ("来た", "き"),
        ("来て", "き"), ("来ない", "こ"), ("来なかった", "こ"), ("来られ", "こ"),
        ("来い", "こ"), ("来よう", "こ"), ("来れば", "く"), ("来させ", "こ"),
    ],
}


def stem_and_endings(surface: str, pos: tuple[str, ...]) -> tuple[str, str] | None:
    """Return (stem, possible_next_chars) or None if the word does not inflect.

    An empty `possible_next_chars` means the stem alone is a sufficient rule.
    """
    for p in pos:
        if p in GODAN_ENDINGS:
            if len(surface) < 2:
                return None
            stem = surface[:-1]
            if not stem:
                return None
            return stem, GODAN_ENDINGS[p]
        if p in ("v1", "v1-s"):
            if len(surface) < 2:
                return None
            stem = surface[:-1]
            if not stem:
                return None
            # stem already carries okurigana -> unambiguous on its own
            return (stem, "") if _is_kana(stem[-1]) else (stem, ICHIDAN_NEXT)
        if p in ("adj-i", "adj-ix"):
            if len(surface) < 2:
                return None
            stem = surface[:-1]
            if not stem:
                return None
            return (stem, "") if _is_kana(stem[-1]) else (stem, ADJ_I_NEXT)
    return None


def _is_kana(ch: str) -> bool:
    from .kana import is_kana

    return is_kana(ch)


def is_inflecting(pos: tuple[str, ...]) -> bool:
    return any(p in VERB_POS for p in pos)
