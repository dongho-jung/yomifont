"""Shaping test corpus.

Each case is (text, [(span_text, expected_reading), ...]) where the expected
readings are listed in the order their ruby appears in the glyph stream.
`None` for the list means "no assertion, just must not crash".
"""

# The sentences named in the project brief, plus the PoC vocabulary.
SENTENCES = [
    ("私は昨日東京へ行きました。", [("私", "わたし"), ("昨日", "きのう"),
                                    ("東京", "とうきょう"), ("行", "い")]),
    ("日本語を勉強しています。", [("日本語", "にほんご"), ("勉強", "べんきょう")]),
    ("今日の天気はいいですね。", [("今日", "きょう"), ("天気", "てんき")]),
    ("大人になってから分かりました。", [("大人", "おとな"), ("分", "わ")]),
    ("市場を調査しています。", [("市場", "しじょう"), ("調査", "ちょうさ")]),
    ("人気のない山道を歩いた。", [("人気", "にんき"), ("山道", "やまみち"), ("歩", "ある")]),
    ("この商品は人気があります。", [("商品", "しょうひん"), ("人気", "にんき")]),
    ("ご飯を食べました。", [("飯", "はん"), ("食", "た")]),
    ("この行いは正しい。", [("行", "おこな"), ("正", "ただ")]),
    ("銀行へ行った。", [("銀行", "ぎんこう"), ("行", "い")]),
]

# PoC-level invariants: these are the architectural claims, not corpus accuracy.
POC = [
    # PoC 1 -- a single lexical word gets group ruby
    ("東京", [("東京", "とうきょう")]),
    # PoC 2 -- reusable ruby glyphs across different words
    ("京都", [("京都", "きょうと")]),
    ("今日", [("今日", "きょう")]),
    # PoC 3 -- okurigana context selects the reading of the same kanji
    ("行く", [("行", "い")]),
    ("行う", [("行", "おこな")]),
    ("食べる", [("食", "た")]),
    ("食う", [("食", "く")]),
    # PoC 4 -- longest match
    ("日本", [("日本", "にほん")]),
    ("日本語", [("日本語", "にほんご")]),
    ("日本人", [("日本人", "にほんじん")]),
    # multi-group words: two ruby groups emitted from one substitution
    ("取り戻す", [("取", "と"), ("戻", "もど")]),
    ("申し込み", [("申", "もう"), ("込", "こ")]),
    # inflection reaches forms JMdict does not list
    ("書きました", [("書", "か")]),
    ("書かない", [("書", "か")]),
    ("書いて", [("書", "か")]),
    ("食べさせられました", [("食", "た")]),
    ("新しくない", [("新", "あたら")]),
    ("勉強しました", [("勉強", "べんきょう")]),
    # irregular verb whose kanji reading changes across the paradigm
    ("来る", [("来", "く")]),
    ("来ない", [("来", "こ")]),
    ("来ました", [("来", "き")]),
]

# Text that must produce NO ruby at all (kana-only, latin, punctuation).
NO_RUBY = [
    "ひらがなだけ",
    "カタカナダケ",
    "hello world",
    "、。！？",
    "",
]
