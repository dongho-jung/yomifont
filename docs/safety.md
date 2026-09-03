# The safe-reading policy

> If YomiFont shows a reading, that reading should be correct.

Phase 1 optimised coverage: every conflict was resolved by picking the most
frequent candidate, so 99.97 % of kanji tokens got ruby and 4.6 % of them were
wrong. Phase 2 inverts that. **Precision first, coverage second.** A word whose
reading is not determined by anything a shaping engine can see gets no ruby at
all, and that is the intended behaviour rather than a gap.

## The classifier

`src/yomifont/safety.py`. The load-bearing signal is **entry identity** — which
dictionary entry a reading comes from, not how common it is.

```
今日   きょう / こんにち     one JMdict entry   -> variant readings of one lexeme -> SAFE
行く   いく   / ゆく         one entry          -> SAFE
市場   しじょう / いちば     two entries        -> two different words -> AMBIGUOUS
人気   にんき / ひとけ       two entries        -> AMBIGUOUS
生物   せいぶつ / なまもの   two entries        -> AMBIGUOUS
```

Two readings inside one entry are alternative pronunciations of one word;
printing the prominent one is not an error. Two readings in two entries are two
different words sharing a spelling, and nothing in the glyph run distinguishes
them.

**Corpus frequency is not consulted when deciding what a word reads.** A corpus
can tell you which reading is more common; it cannot tell you the other one is
wrong. Phase 1's UniDic priors and the hand-written override table are both
gone from the reading decision.

### States

| state | meaning | outcome |
|---|---|---|
| `SAFE_UNIQUE` | every live entry for this surface agrees on the reading | rule emitted |
| `SAFE_CONTEXTUAL` | resolved by okurigana visible to the shaper (verb stems) | rule emitted |
| `AMBIGUOUS` | live entries disagree | no ruby, and a **block rule** so nothing shorter fires |
| `UNSAFE_ALIGNMENT` | reading exists but cannot be aligned to the spelling | no ruby |
| `UNSUPPORTED_SHAPER_CONTEXT` | determined only by context an engine hides (Blink) | no ruby |
| `OUT_OF_SCOPE` | not in the lexicon | no ruby |

### Abstention has to be enforced, not just omitted

Dropping a rule is not the same as abstaining. 難しい is ambiguous, but with no
rule covering it the single-character 難 rule matched instead and printed なん.
A **block rule** — a context rule that matches the sequence and substitutes
nothing — consumes the span and emits no ruby, which is what abstention has to
mean at the shaping layer.

## What the classifier caught

Four bugs with wide blast radius, each found by classifying the error corpus
rather than by inspection:

**`misc` is a sense-level field.** Unioning it across an entry's senses marked
僕/ぼく dead (one archaic sense among several) and handed 僕 to しもべ. Same for
難しい, 通る, 少女, 大丈夫, 国 and 子. An entry counts as dead only when *every*
sense is marked dead. This one fix moved precision from 93.7 % to 96.4 %.

**Ambiguity is inherited by inflected forms.** Blocking 強い while leaving
強く unblocked let the 強 rule print きょう. An ambiguous word's whole paradigm
is blocked.

**A lexical entry outranks a derived form, but only when they agree.** 同じ is
the adjective おなじ, not the 連用形 of the rare 同じる (どうじる) — a direct
entry for exactly this surface is stronger evidence. When the two disagree and
neither is structurally preferable (説明し = 説明+し or the noun ときあかし),
both lose.

**Okurigana-less spelling variants.** JMdict lists 気持 and 気持ち under one
entry, both read きもち; 気持 is just the spelling without okurigana. Keeping it
put きもち over two characters and left ち bare. Dropping the abbreviated form
removed the whole class — 金持, 支払, 年寄, 見舞, 手洗, 目指, 腰掛.

## Proper nouns are included, by determinism not by category

The rule is *"is there exactly one safe reading?"*, not *"is this a name?"*.
東京 → とうきょう, 富士山 → ふじさん and 任天堂 → にんてんどう are all fine.

JMnedict was measured before being trusted. Its own multi-reading rate per name
type says how much a single listed reading is worth:

| type | surfaces | already multi-read |
|---|---|---|
| station | 8,255 | **0.11 %** |
| organization | 4,768 | 0.96 % |
| person (full name) | 49,662 | 1.97 % |
| work | 751 | 3.86 % |
| company | 653 | 5.97 % |
| place | 191,927 | 11.20 % |
| fem | 82,194 | 21.65 % |
| masc | 18,419 | 27.59 % |
| unclass | 75,234 | 29.51 % |
| surname | 100,389 | **33.06 %** |
| given | 50,250 | **36.72 %** |

Where a third of all spellings are *already known* to be multi-read, an entry
listing one reading is far more likely to be incomplete data than evidence of
uniqueness. So place-like types are admitted and person-name types are not —
except for surfaces that exist **only** as names, where all types vote, because
otherwise excluding surnames hands 田中 to the Chinese place reading
てぃえんじょん instead of たなか.

**JMnedict extends the lexicon; it never vetoes it.** Its own DTD calls it "a
quick-and-dirty conversion of the ENAMDICT entries", and admitting it as a
competitor deletes 450 EDRDG-common words to obscure homograph hamlets —
下宿 (げしゅく) to したじゅく, 東京 to とうけい. Measured, then decided.

## Deliberate coverage losses

Each of these was measured before being taken.

**Single-character rules — dropped entirely.** A lone kanji's reading is
determined only when it stands alone, and the font cannot tell: inside an
unknown compound the same rule fires and prints the free-standing reading
(蓮花 → はす + はな). Guarding it needs both a backtrack and a lookahead, which
then fails at the start of every shaping run — and in Blink every lone kanji
*is* at the start of its run. Cost: **4.4 points of coverage**; benefit:
**26 of 59 remaining wrong readings removed**.

**Stems that collide with case particles.** 雪ぐ (すすぐ) generates a 雪が rule
that beats 雪 + が in "雪が降る". Dropped when the stem is itself a known word.

**Words plus particles.** 今日は is a real entry (こんにちは) and, being longer,
always beats 今日 — longest match is rule order and no priority can outrank it.
Removed rather than down-ranked.

**All-Han stems of inflecting verbs.** 微笑 is the noun びしょう and also the
stem of 微笑む (ほほえ). Under Blink's script segmentation the Han run is just
微笑 and nothing downstream can separate them, so the prefix rule is dropped.
Cost: 0.65 points of coverage; benefit: **219 fewer Blink errors**.

## Remaining wrong readings

31 in 20,000 held-out sentences, and they are one class: **a common noun that
is also somebody's name.**

```
陽子   ようし (proton)     / ようこ (given name)
平野   へいや (plain)      / ひらの (surname)
高木   こうぼく (tall tree)/ たかぎ (surname)
立花   りっか              / たちばな (surname)
牧野   ぼくや              / まきの (surname)
上野   こうずけ (province) / うえの (place)
千歳   せんざい            / ちとせ (place)
```

These cannot be driven to zero by admitting person names as competitors,
because JMnedict is not allowed to veto JMdict — and the evidence above says it
must not be. The font sees 陽子 and cannot know whether the sentence is about
physics or about a woman named Yōko. This is the semantic wall, and it is where
abstention would require exactly the sentence-level understanding the project
does not have.

The full machine-readable list is `data/normalized/error_corpus.json`, with a
deterministic root-cause class on every entry.
