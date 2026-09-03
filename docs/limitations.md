# Limitations

The goal of this project is to find out **how far automatic furigana can be
pushed inside an OpenType font**, not to make every kanji get a reading. Some
of what follows is fixable engineering; some of it is a wall. The two are
labelled.

---

## Walls: things a font cannot do

A shaping engine sees a run of glyphs and nothing else. It has no sentence, no
syntax, no world knowledge, and — in Blink — not even the okurigana. These are
not bugs to be fixed later.

### Readings that depend on meaning

```
人気   にんき (popularity)   /  ひとけ (sign of life)
市場   しじょう (market, economic) /  いちば (marketplace, physical)
生物   せいぶつ (organism)   /  なまもの (raw food)
今日   きょう (today)        /  こんにち (nowadays)
何     なに                  /  なん   (before certain consonants)
時     とき (time)           /  じ (o'clock)
```

Both readings are correct Japanese; only the sentence decides. YomiFont picks
the more frequent one and will be confidently wrong the rest of the time.
10,558 of 204,917 distinct surfaces (5.2 %) have more than one reading;
9,364 are decidable by frequency and **1,194 are genuine ties**.

`--abstain-margin 1.02` drops rules whose runner-up reading is within 2 % of
the winner (1,446 rules), emitting no ruby instead of a guess. Measured effect
on the corpus is within noise (92.44 % → 92.46 % correct, coverage 99.97 % →
99.96 %), because near-ties are rare in running text — but it is the right
switch if you would rather have nothing than a wrong reading.

### Proper nouns

JMdict is a general dictionary; names live in JMnedict, which is not used here.
An unknown place or person name decomposes into per-character rules and
produces a plausible-looking wrong reading:

```
新宿          →  あたら + やど            (correct: しんじゅく)
東京都新宿区   →  とうきょうと + あたら + やど + く
```

`東京都` and long institutional compounds that *are* in JMdict come out right
(`日本語能力試験` → にほんごのうりょくしけん, `国際交流基金` →
こくさいこうりゅうききん); it is specifically the unknown name that decomposes.
Note also that the single-kanji fallback makes the failure *look* more wrong
than the alternative — 新 falls back to its verb-stem reading あたら rather than
しん — because that fallback is tuned for Blink, where it is right far more
often. Both are wrong for 新宿; neither is recoverable without a name list.

Adding JMnedict would fix the coverage but not the ambiguity — Japanese names
are the hardest reading problem there is, and 山崎 is やまざき or やまさき
depending on the person.

### Okurigana context in Blink

Chrome shapes each script run separately, so `行く` and `行う` are
indistinguishable there — both are just `行`. See
[compatibility.md](compatibility.md). Nothing in the font can recover this;
it is decided before the font is consulted.

### Sentence-level phenomena

Rendaku across a word boundary, counter readings that depend on the counted
noun (一日 = ついたち or いちにち), and numerals generally
(`６時` → ろくじ vs `6` + `時`) all need information the glyph run does not
carry.

---

## Measured accuracy

20,000 held-out Tatoeba sentences, 79,321 kanji-bearing tokens, scored against
UniDic. Training data for the corpus priors was sentences 20,000–150,000, so
the evaluation set was never seen.

| | HarfBuzz / CoreText | Blink |
|---|---|---|
| tokens that got ruby | 99.97 % | 99.76 % |
| **correct reading** | **92.44 %** | **91.12 %** |
| wrong reading | 4.29 % | 7.00 % |
| ruby present but unscorable | 3.24 % | 1.88 % |
| no ruby | 0.03 % | 0.24 % |

Of the span-level disagreements with UniDic:

- **2.90 %** — a different reading that JMdict *does* attest for that word.
  Often YomiFont is right and the oracle's lemma convention is not
  (私 → わたし vs UniDic's ワタクシ; 日曜日 → にちようび vs UniDic's
  per-token concatenation にちようひ).
- **3.01 %** — deliberate overrides where YomiFont disagrees with UniDic on
  purpose. Listed with reasons in `data/overrides.tsv`.
- **1.03 %** — a reading **not attested** for that word at all. This is the
  real defect rate, and it is almost entirely stem rules for rare verbs
  shadowing a noun (雪ぐ's `雪が` beating 雪 + が).

## Fixable engineering, not yet done

**Vertical writing.** Ruby placement is baked in as horizontal offsets, so
tategaki gets no furigana (the font blanks it under `vert` rather than
scattering it). A second positional inventory with vertical offsets would fix
this.

**GSUB is rebuilt from scratch.** The base font's `locl`, `jp78/83/90`, `nlck`
and `hwid/fwid` features are dropped; only `vert`/`vrt2` punctuation forms are
carried across. Merging into the base font's existing GSUB is straightforward
but was not needed for the research question.

**Font size.** 11.3 MB is large for a web font. The 50k-rule build is 2.2 MB
and covers the common vocabulary. Real compression work — sharing rule suffixes,
trie-style factoring of the ChainSubRuleSets — has not been attempted.

**Build time above 300k rules.** HarfBuzz's repacker fails somewhere between a
8.7 MB and 9.2 MB GSUB, and fontTools' fallback takes 4.5× longer (84 s vs
19 s). The output is valid either way.

**No JMnedict, no pitch accent, no weights other than Regular.**

**109 unalignable JMdict entries** (0.05 %) — colloquial spellings like
`こう言う / こーゆー` where the kana in the surface simply do not appear in the
reading. Correctly rejected rather than mis-aligned.

## Things that are deliberately not attempted

Per the project's scope: no runtime analyzer, no text preprocessing, no
JavaScript, no HTML ruby, no browser extension. Every reading decision is
frozen into the font at build time. That constraint is the whole point — the
question being answered is what survives it.
