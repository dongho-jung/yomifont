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

# Stabilization-pass regressions. Each one was a specific defect; the comment
# is the mechanism, not the symptom, so the test still means something if the
# rule set changes underneath it.
STABILIZATION = [
    # ヶ is not okurigana: it abbreviates 箇 and carries its own reading, so
    # anchoring it as a kana ate the か. Was いっ + ヶ + げつ.
    ("一ヶ月", ["いっかげつ"]),
    # a kana the aligner anchors gets no ruby and is displayed as itself, so
    # anchoring が to a reading's か printed the wrong mora. Was じがん.
    ("時間", ["じかん"]),
    ("失敗", ["しっぱい"]),
    ("芝生", ["しばふ"]),
    # JMnedict place names, admitted because their readings are determined.
    ("新宿区", ["しんじゅくく"]),
    ("東京都", ["とうきょうと"]),
    # proper nouns whose reading is settled in practice, even where JMnedict
    # lists obscure homographs: 新宿 also names hamlets read あらじゅく,
    # しんしく, しんしゅく and にいじゅく, none of which anyone writes.
    ("新宿", ["しんじゅく"]),
    ("六本木", ["ろっぽんぎ"]),
    ("秋葉原", ["あきはばら"]),
    ("浅草", ["あさくさ"]),
    ("原宿", ["はらじゅく"]),
    ("渋谷", ["しぶや"]),
    ("渋谷区", ["しぶやく"]),
    ("千代田区", ["ちよだく"]),
    ("東京都新宿区", ["とうきょうと", "しんじゅくく"]),
    ("東京都渋谷区", ["とうきょうと", "しぶやく"]),
    # a larger lexical unit must beat constituent readings
    ("月曜日", ["げつようび"]),
    ("今月", ["こんげつ"]),
    ("来月", ["らいげつ"]),
    ("日本語能力試験", ["にほんごのうりょくしけん"]),
    ("国際交流基金", ["こくさいこうりゅうききん"]),
]

# Surfaces that must render NOTHING, with the reason they are undetermined.
STABILIZATION_ABSTAIN = [
    ("月", "つき / げつ / がつ -- polyphonic, and no context resolves it"),
    ("一月", "two entries: いちがつ (the month) and ひとつき / いちげつ (a month)"),
    ("上野", "こうずけ in the dictionary, うえの in running text"),
    ("居る", "the lexicon lists only おる; a corpus shows いる"),
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

# --------------------------------------------------------------------------
# Author-supplied ruby (｜BASE（RUBY）｜) was built and then removed: it worked,
# but marking up every word by hand was more trouble than it was worth, and its
# glyph inventory was 31,701 of the font's 63,070 glyphs.  What has to survive
# the removal is that the delimiters it used are once again ordinary characters:
# brackets and vertical bars must reach the reader exactly as typed, with no
# ruby of their own and nothing swallowed.
PUNCTUATION_INTACT = [
    "私（わたし）",
    "価格（税別）",
    "月（ライト）",
    "（ですます）",
    "小説《ノルウェイの森》",
    "表｜裏",
    "第一｜第二",
    "a|b|c",
    "f(x) = |x| + 1",
    "｜月（ライト）｜",
]

# Text that must produce NO ruby at all.
NO_RUBY = [
    "ひらがなだけ",
    "カタカナダケ",
    "hello world",
    "、。！？",
    "",
]
