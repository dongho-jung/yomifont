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

Every wall in this section is a wall for *inferring* a reading. None of them
applies once the author writes the reading down: `｜人気（ひとけ）` renders
ひとけ, and `｜生物（なまもの）` renders なまもの, because nothing is being
inferred. [explicit-ruby.md](explicit-ruby.md) covers what that costs and where
it works — notably that Blink's script segmentation limits it to kana bases.

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

This is the only class that still produces **wrong** readings — 31 of them in
20,000 sentences:

```
陽子   ようし (proton)      / ようこ (given name)
平野   へいや (plain)       / ひらの (surname)
高木   こうぼく (tall tree) / たかぎ (surname)
立花   りっか               / たちばな (surname)
上野   こうずけ (province)  / うえの (place)
千歳   せんざい             / ちとせ (place)
```

They cannot be abstained away by admitting person names as competitors: doing
so would let JMnedict veto JMdict, and that deletes 450 EDRDG-common words to
obscure homograph hamlets (下宿 → したじゅく, 東京 → とうけい). The evidence for
that decision is in [safety.md](safety.md). The font sees 陽子 and cannot know
whether the sentence is about physics or about a woman named Yōko.

Full machine-readable list: `data/normalized/error_corpus.json`.

### Unknown proper nouns

JMnedict integration works and is measured, but it cannot be shipped as one font
(see below), so the default build has JMdict names only. A name outside the
lexicon simply gets no ruby — Phase 1 would have decomposed 新宿 into
あたら + やど; Phase 2 renders nothing.

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
| core (JMdict) | 300,364 | 1,375 | yes |
| + JMnedict | 738,030 | **8,547** | **no** |

`LookupList` offsets are `Offset16` from the list start, capping the total at
roughly 3,000–3,600 small lookups. Extension lookups solve *subtable* offsets,
not this one. Splitting the rule set across two `ccmp` lookups would work but
needs a partition where no first glyph appears in both, or a word could receive
ruby twice.

## Measured, honest numbers

| | HarfBuzz / CoreText | Blink model |
|---|---|---|
| precision (of rendered readings) | **99.942 %** | 99.868 % |
| wrong readings | **31** | 45 |
| coverage | 79.07 % | 48.92 % |
| strict precision (oracle conventions counted as errors) | 96.56 % | — |

The gap between 99.94 % and the strict 96.56 % is 1,807 spans where YomiFont and
UniDic disagree but YomiFont is not wrong: the oracle picked a different reading
of the same lexeme (明日 = あした vs あす), or its tokenizer split a word and
concatenated per-token readings, losing rendaku (日曜日 → にちようひ). Both
numbers are reported so the assumption is visible.

## Fixable engineering, not yet done

**Chrome regression, unresolved.** One controlled measurement showed Chrome 152
rendering no ruby with the Phase 2 font while rendering it correctly with the
Phase 1 font. Not reproduced since; see [compatibility.md](compatibility.md).
This is the highest-priority open item.

**Vertical writing.** Ruby placement is baked in as horizontal offsets, so
tategaki renders with furigana suppressed rather than scattered.

**GSUB is rebuilt from scratch**, dropping the base font's `locl`, `jp78/83/90`,
`nlck` and width features; only `vert`/`vrt2` punctuation forms are carried
across.

**Font size.** 15.3 MB, and the 60k-rule web build is 5.5 MB. Two separate
costs stack up here:

* the finer placement grid and three ruby sizes cost 14,486 automatic ruby
  glyphs against Phase 1's 3,262;
* widening the kanji repertoire so explicit ruby can take bases the dictionary
  never mentions adds ~5,900 real kanji outlines — **about 3.4 MB, more than
  every explicit ruby glyph put together** (32,391 of them, 0.7 MB, because
  ruby glyphs are composites and kanji are not).

That second cost is what `--no-explicit-bases` turns off, and it is what makes
the web build viable. Suffix sharing across `ChainSubRule`s is still untried.

**Build time above ~300k rules** degrades sharply: the HarfBuzz repacker fails
around an 8.7 MB GSUB and fontTools' fallback takes 4–5× longer.

**Mono-ruby and jukugo-ruby**, per-kana optical spacing, and true ruby-specific
outlines — see [typography.md](typography.md).

## Deliberately not attempted

No runtime analyzer, no text preprocessing, no JavaScript, no HTML ruby, no
browser extension. Every reading decision is frozen into the font at build time.
That constraint is the point.
