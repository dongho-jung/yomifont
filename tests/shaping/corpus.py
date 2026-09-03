"""Shaping test corpus (Phase 2).

Each case is (text, [expected reading, ...]) in the order the ruby appears.
An empty list means "no ruby at all" -- which for Phase 2 is a first-class
expected outcome, not a gap.
"""

# The architectural claims. These assert mechanism, not corpus accuracy.
POC = [
    # a lexical word gets group ruby
    ("東京", ["とうきょう"]),
    ("京都", ["きょうと"]),
    ("今日", ["きょう"]),
    ("学校", ["がっこう"]),
    ("図書館", ["としょかん"]),
    # okurigana context selects between readings of the same kanji
    ("行く", ["い"]),
    ("行う", ["おこな"]),
    ("食べる", ["た"]),
    # longest match
    ("日本", ["にほん"]),
    ("日本語", ["にほんご"]),
    ("日本人", ["にほんじん"]),
    # two ruby groups from one substitution
    ("取り戻す", ["と", "もど"]),
    ("申し込み", ["もう", "こ"]),
    # inflection reaches forms JMdict does not list
    ("書きました", ["か"]),
    ("書かない", ["か"]),
    ("食べさせられました", ["た"]),
    ("勉強しました", ["べんきょう"]),
    # long compounds stay one lexical group
    ("日本語能力試験", ["にほんごのうりょくしけん"]),
    ("国際交流基金", ["こくさいこうりゅうききん"]),
]

# Phase 2 abstentions: these MUST render no ruby, because the reading is not
# determined by anything a shaping engine can see.
ABSTAIN = [
    ("市場", "しじょう / いちば"),
    ("人気", "にんき / ひとけ"),
    ("生物", "せいぶつ / なまもの"),
    ("大人", "おとな / たいじん / だいにん"),
    ("人", "ひと / じん / にん"),
    ("時", "とき / じ"),
    ("中", "なか / ちゅう"),
    ("強い", "つよい / こわい"),
    ("行った", "いった / おこなった"),
    ("僕", "ぼく / しもべ"),
    ("大丈夫", "だいじょうぶ / だいじょうふ"),
]

SENTENCES = [
    ("私は昨日東京へ行きました。", ["きのう", "とうきょう", "い"]),
    ("日本語を勉強しています。", ["にほんご", "べんきょう"]),
    ("今日の天気はいいですね。", ["きょう", "てんき"]),
    ("銀行へ行った。", ["ぎんこう"]),
]

# Text that must produce NO ruby at all.
NO_RUBY = [
    "ひらがなだけ",
    "カタカナダケ",
    "hello world",
    "、。！？",
    "",
]
