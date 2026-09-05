# Limitations

YomiFont displays furigana for lexical readings that can be safely determined at
the font shaping layer, and intentionally abstains when the reading is
ambiguous. It is **not** automatic reading of arbitrary Japanese.

About a fifth of the kanji tokens in ordinary prose get no ruby, and in Chrome
about half do. That is the design, not a gap: a wrong reading is worse for a
reader than a missing one.

## Where the abstentions come from

20,000 held-out Tatoeba sentences, 79,321 kanji-bearing tokens:

| | tokens | share |
|---|---|---|
| ruby rendered | 62,716 | 79.1 % |
| abstained — surface is lexically ambiguous | 11,580 | 14.6 % |
| abstained — safe, but no rule reaches this span | 4,156 | 5.2 % |
| abstained — not in the lexicon at all | 869 | 1.1 % |

"Safe but no rule" is mostly the single-character rules that were removed, plus
spans a longer rule consumed differently than the tokenizer did.

## Walls: things a font cannot do

A shaping engine sees a run of glyphs and nothing else — no sentence, no syntax,
no world knowledge, and in Blink not even the okurigana.

Every wall in this section is a wall for *inferring* a reading, and an author
who writes the reading down is not inferring anything. YomiFont had a syntax
for that — `｜人気（ひとけ）｜`, resolved entirely in GSUB — and it worked, in
Chrome included. It was removed anyway: annotating each word by hand was more
trouble than it was worth for the readings it recovered, and the inventory it
needed was 31,701 glyphs, half the font. The commit is `6ca0452`.

### Readings that depend on meaning

```
人気   にんき (popularity)      / ひとけ (sign of life)
市場   しじょう (market)        / いちば (marketplace)
生物   せいぶつ (organism)      / なまもの (raw food)
大人   おとな                   / たいじん / だいにん
時     とき (time)              / じ (o'clock)
中     なか (inside)            / ちゅう (during)
```

2,324 of 197,831 JMdict surfaces (1.2 %) have competing readings across
entries. They are the 14.6 % of tokens above, because the ambiguous words are
disproportionately common ones.

### Common nouns that are also names

This is the only class that still produces **wrong** readings — 21 of them in
20,000 sentences, down from 31. A JMnedict person-name reading now vetoes a
JMdict word *when EDRDG has not marked that word common*, which removes ten of
them (上野 こうずけ, 平野 へいや, 陽子 ようし). The qualifier is necessary:
without it JMnedict's やまと for 日本 and みやこ for 京都 delete both words.
What is left is the case where both readings are common — 千歳 せんざい /
ちとせ, 立花 りっか / たちばな — and nothing visible to the font separates them.
Abstaining on those too was measured at 8 wrong readings and 73.9 % coverage;
it also removes 日本 and 京都, which is why it is not the default
(`safety.PERSON_NAMES_VETO`).

```
陽子   ようし (proton)      / ようこ (given name)
平野   へいや (plain)       / ひらの (surname)
高木   こうぼく (tall tree) / たかぎ (surname)
立花   りっか               / たちばな (surname)
上野   こうずけ (province)  / うえの (place)
千歳   せんざい             / ちとせ (place)
```

The font sees 陽子 and cannot know whether the sentence is about physics or
about a woman named Yōko. Toponym competitors are still refused outright —
JMnedict knows a hamlet for nearly every word, and admitting those deletes 450
EDRDG-common words (下宿 → したじゅく, 東京 → とうけい); the evidence is in
[safety.md](safety.md).

Full machine-readable list: `data/normalized/error_corpus.json`.

### Known names the rule set does not carry

Rules are correct one at a time and can still compose wrongly. 六本木 is
ろっぽんぎ; the shipped subset has no rule for it, so 六本 fires and the reader
gets ろっぽん over 六本 with 木 bare. `audit_readings.py` cannot see this,
because 六本 → ろっぽん is a perfectly good rule.

Composition failures split in two, and only one of them is an error:

* **partial but consistent** — 公園 → こうえん inside あいの里公園, 六本 →
  ろっぽん inside 六本木. The ruby shown is right for the span it covers; what
  is missing is ruby on the rest. Left alone.
* **contradicting** — 立花 as りっか inside いよ立花駅 (たちばな), 小屋 as こや
  inside くろがね小屋 (ごや). 15,600 of these now get a **block rule**, so they
  render nothing instead of something wrong.

Blocking is nearly free in the resource that bounds the build: block rules
share one MultipleSubst output per first glyph, so the lookup count is
unchanged at 2,038. It is not free in the ChainSubRuleSet, which is why 大
(already 3,932 rules and ~78 kB before any blocks) takes none — a first glyph
with no room keeps the behaviour it has today rather than costing everything
else a build.

### Unknown proper nouns

**153,745 place-like JMnedict names now ship.** Admitting all of them needs
6,175 MultipleSubst lookups against a ceiling near 3,200, so it does not build
— but that cost is not spread out. Of 4,910 first glyphs the median needs 10
lookups and only **seven** exceed the cap: 大, 上, 下, 西, 東, 小, 中, each
starting thousands of 大字○○-style rural hamlets. Capping per first glyph keeps
essentially every name anyone would write and drops 15,308 from the tail of
those seven (`rules.fit_lookup_budget`). Two ceilings apply independently: the
global lookup count, and the per-glyph ChainSubRuleSet, whose ChainSubRule
offsets are Offset16 from the set's start.

新宿 is the case that forced the question. JMnedict gives it five entries —
あらじゅく, しんしく, しんしゅく, しんじゅく, にいじゅく — all typed `place`,
all priority 0, so nothing in the lexical data ranks them; four are hamlets
nobody writes about. Treating that as undetermined loses 新宿, and 新宿 is
しんじゅく. So for **proper nouns only**, where the corpus attests exactly one
of the listed readings, that reading is taken (`safety.NAME_CORPUS_DISAMBIGUATION`).
This is the one place corpus evidence *selects* rather than only removes, and
it is fenced: JMnedict-only surfaces, and the reading still has to come from
the lexicon. A word JMdict knows never reaches it, so 日本 and 京都 are decided
as before.

That trade is measured: precision 99.961 % → 99.963 %, coverage 78.9 % → 79.1 %,
wrong readings 21 → 20.

### Okurigana context in Blink

Chrome shapes each script run separately, so `行く` and `行う` are
indistinguishable there — both are just `行`, which has no rule. Nothing in the
font can recover this; it is decided before the font is consulted.

## Hard scaling limit found

The JMnedict build (738,030 rules) **does not compile**. fontTools names it:

> GSUB LookupList offset overflowed and all lookups are already Extension
> lookups, so the overflow can't be resolved by promotion; reduce the number of
> lookups.

The binding constraint is not the rule count but the **lookup count**. A
MultipleSubst subtable is keyed by glyph, so it holds one output per glyph; the
number of lookups needed equals the maximum number of distinct ruby outputs for
any single first character.

| build | rules | MultipleSubst lookups | compiles |
|---|---|---|---|
| JMdict only | 300,364 | 1,375 | yes |
| **+ administrative place names** (shipping) | **325,492** | **2,039** | **yes** |
| + all place-like JMnedict | 481,490 | 6,304 | no |
| + all JMnedict | 738,849 | 8,694 | no |

`LookupList` offsets are `Offset16` from the list start, capping the total at
roughly 3,000–3,600 small lookups. Extension lookups solve *subtable* offsets,
not this one. Splitting the rule set across two `ccmp` lookups would work but
needs a partition where no first glyph appears in both, or a word could receive
ruby twice.

## Measured, honest numbers

| | HarfBuzz / CoreText | Blink model |
|---|---|---|
| precision (of rendered readings) | **99.961 %** | see compatibility.md |
| wrong readings | **21** | |
| coverage | 78.95 % | |
| strict precision (oracle conventions counted as errors) | 96.6 % | — |

The gap between the headline precision and the strict number is ~1,800 spans where YomiFont and
UniDic disagree but YomiFont is not wrong: the oracle picked a different reading
of the same lexeme (明日 = あした vs あす), or its tokenizer split a word and
concatenated per-token readings, losing rendaku (日曜日 → にちようひ). Both
numbers are reported so the assumption is visible.

## Fixable engineering, not yet done

**Vertical writing.** Ruby placement is baked in as horizontal offsets, so
tategaki renders with furigana suppressed rather than scattered.

**GSUB is rebuilt from scratch**, dropping the base font's `locl`, `jp78/83/90`,
`nlck` and width features; only `vert`/`vrt2` punctuation forms are carried
across.

**Font size.** 20.2 MB, and the 60k-rule web build is 3.9 MB. Almost all of it
is GSUB — 14.7 MB against 4.7 MB of outlines — so the rule set is the lever,
which is what the web build pulls. Carrying every kanji Noto Sans JP can draw,
rather than only the ones the rules mention, is the other 3.5 MB and what
`--minimal-repertoire` turns off; it buys not falling back to another face on a
rare character. The finer placement grid and three ruby sizes cost 17,264 ruby
glyphs against Phase 1's 3,262, but those are composites and cheap. Suffix
sharing across `ChainSubRule`s is still untried.

**Build time above ~300k rules** degrades sharply: the HarfBuzz repacker fails
around an 8.7 MB GSUB and fontTools' fallback takes 4–5× longer.

**Mono-ruby and jukugo-ruby**, per-kana optical spacing, and true ruby-specific
outlines — see [typography.md](typography.md).

## Deliberately not attempted

No runtime analyzer, no text preprocessing, no JavaScript, no HTML ruby, no
browser extension. Every reading decision is frozen into the font at build time.
That constraint is the point.
