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
# Explicit Ruby: ｜BASE（RUBY） / |BASE(RUBY)
#
# (text, base length in em, reading).  The reading is asserted as one string
# rather than as groups: an explicit expression is always exactly one group,
# and `ruby_runs` splits a widely distributed group (two kana over a three
# character base) on its inter-kana gap, which is correct for the automatic
# side and meaningless here.
EXPLICIT = [
    ("｜月（ライト）", 1, "ライト"),
    ("｜宇宙（そら）", 2, "そら"),
    ("｜本気（マジ）", 2, "マジ"),
    ("｜強敵（とも）", 2, "とも"),
    ("｜東京（とうきょう）", 2, "とうきょう"),
    ("｜日本語能力試験（にほんごのうりょくしけん）", 7, "にほんごのうりょくしけん"),
    # the reading wins over the dictionary, however unusual
    ("｜東京（エド）", 2, "エド"),
    ("｜猫（いぬ）", 1, "いぬ"),
    # no dictionary is consulted, so an unseen base works
    ("｜超絶暗黒剣（ダークネスブレード）", 5, "ダークネスブレード"),
    ("｜未知語（オリジナルヨミ）", 3, "オリジナルヨミ"),
    # kana, Latin and digits are all admissible as *bases*
    ("｜ほんき（マジ）", 3, "マジ"),
    ("｜AI（エーアイ）", None, "エーアイ"),
    ("｜2026（にせんにじゅうろく）", None, "にせんにじゅうろく"),
    # the whole supported ruby alphabet
    ("｜阿（ぁぃぅぇぉっゃゅょ）", 1, "ぁぃぅぇぉっゃゅょ"),
    ("｜阿（ガギグゲゴパピプペポ）", 1, "ガギグゲゴパピプペポ"),
    ("｜阿（ヴーヽヾ・）", 1, "ヴーヽヾ・"),
    # limits
    ("｜一二三四五六七八（あ）", 8, "あ"),
]

# The Aozora form: 〇BASE《RUBY》, and the marker is optional when the base is
# a run of kanji. This is the form that survives Blink's run split, because it
# compiles to two rules that never have to see each other.
EXPLICIT_SPLIT = [
    ("〇月《ライト》", 1, "ライト"),
    ("〇東京《エド》", 2, "エド"),
    ("〇宇宙《そら》", 2, "そら"),
    ("〇強敵《とも》", 2, "とも"),
    ("〇日本語能力試験《にほんごのうりょくしけん》", 7, "にほんごのうりょくしけん"),
    ("〇超絶暗黒剣《ダークネスブレード》", 5, "ダークネスブレード"),
    ("〇ほんき《マジ》", 3, "マジ"),
    ("〇AI《エーアイ》", None, "エーアイ"),
]

# 《》 without the marker is ordinary text and must survive intact. The marker
# is required precisely because the first run cannot see whether a reading
# follows: an inferring rule hid the 《 of 小説《ノルウェイの森》.
SPLIT_UNMARKED = [
    "小説《ノルウェイの森》", "雑誌《週刊誌》", "《重要》", "曲《ひまわりの約束》",
]

# The ASCII syntax must produce an identical glyph stream.
EXPLICIT_ASCII = [
    ("|月(ライト)", "｜月（ライト）"),
    ("|東京(とうきょう)", "｜東京（とうきょう）"),
    ("|強敵(とも)", "｜強敵（とも）"),
    ("|日本語能力試験(にほんごのうりょくしけん)",
     "｜日本語能力試験（にほんごのうりょくしけん）"),
    ("|AI(エーアイ)", "｜AI（エーアイ）"),
]

# Malformed or out-of-range markup must be left exactly as typed -- visible,
# unshaped, and never partially transformed.
EXPLICIT_MALFORMED = [
    ("｜月（ライト", "no closing delimiter"),
    ("｜月ライト）", "no opening delimiter"),
    ("｜（ライト）", "empty base"),
    ("｜月（）", "empty ruby"),
    ("｜（）", "both empty"),
    ("｜月", "marker with no expression"),
    ("月（ライトという意味）", "parentheses alone must never start ruby"),
    ("|月(ライト", "ascii, no closing delimiter"),
    ("|月ライト)", "ascii, no opening delimiter"),
    ("a|b|c", "bare vertical bars in ordinary text"),
    ("f(x) = |x| + 1", "ascii punctuation in ordinary text"),
    ("｜月（漢字）", "ruby characters outside the supported alphabet"),
    ("｜一二三四五六七八九（あ）", "base longer than the limit (9 > 8)"),
    ("｜月（あいうえおかきくけこさしすせそたち）", "ruby longer than the limit (17 > 16)"),
]

# Text that must produce NO ruby at all.
NO_RUBY = [
    "ひらがなだけ",
    "カタカナダケ",
    "hello world",
    "、。！？",
    "",
]
