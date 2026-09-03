# Architecture

```
JMdict_e.gz  (+ JMnedict.xml.gz)
    │  jmdict.py / jmnedict.py   parse; keep only what can affect a reading
    ▼
lexical IR            (surface, reading, ENTRY ID, rank, pos, misc, source)
    │  safety.py        safe-reading classifier            98.8 % of surfaces safe
    │  alignment.py     okurigana alignment -> ruby groups
    │  conjugation.py   invariant stems + ending sets
    │  rules.py         resolution, blocking, abstention
    ▼
rule set              (seq, groups, safety, origin, src)          300,364 rules
    │  layout.py        JLREQ-style ruby placement -> (kana, size, x)
    │  rubyglyphs.py    reusable ruby inventory              14,194 glyphs
    │  gsub.py          ChainContextSubst + MultipleSubst packing
    │  build.py         subset base font, metrics, naming
    ▼
YomiFont-Regular.ttf   11.2 MB, 19,849 glyphs, no GPOS
```

Everything in this pipeline is ordinary deterministic code. There is no
hand-authored word list at all — Phase 1's override table was deleted along with
the frequency priors, because under the Phase 2 policy nothing picks between
competing readings.

The load-bearing addition since Phase 1 is **entry identity**: the IR carries
the source dictionary's `ent_seq`, which is what separates variant readings of
one lexeme (今日 = きょう / こんにち) from two different words sharing a spelling
(市場 = しじょう / いちば). See [safety.md](safety.md).

---

## 1. Lexical IR

JMdict is parsed with a streaming `iterparse`. Only fields that can influence a
reading are kept: `keb`, `reb`, `re_restr`, `ke_inf`/`re_inf`, `ke_pri`/`re_pri`
and sense-level `pos`. Glosses, examples, cross-references, dialect and
language-of-origin are discarded at parse time and never reach the font.

Two parsing details that materially changed results:

- **Entity codes.** JMdict's DTD is inline, so expat expands `&v5k;` to
  "Godan verb with `ku' ending". Every POS test silently failed until the DTD's
  `<!ENTITY>` declarations were read back and the expansion inverted. Before
  the fix, no conjugation rules were generated at all.
- **Reading prominence.** JMdict lists an entry's readings in order of
  prominence, and that order is a better default signal than `re_pri`.
  今日 has きょう first with only `ichi1`, while こんにち carries
  `ichi1 + news1 + nf02`. Phase 2 uses that order to pick *within* an entry;
  it never uses it to pick *between* entries.
- **`misc` is a SENSE-level field.** Unioning it across an entry's senses marks
  僕/ぼく dead because one of its senses is archaic, and hands 僕 to しもべ.
  Same for 難しい, 通る, 少女, 大丈夫, 国 and 子. Keeping the intersection —
  dead only when every sense is dead — moved precision from 93.7 % to 96.4 %.

## 2. Okurigana alignment

The surface is cut into maximal runs of kana and of ruby-bearing characters.
Kana runs are *anchors*: they must be found in the reading, allowing rendaku
(は→ば), gemination (く→っ), long-vowel spellings (ー↔vowel) and the ヶ
counter. A depth-first search over "how many morae does this run consume",
shortest first, resolves the rest.

```
食べる  / たべる      →  食=た                       べる is already kana
取り戻す / とりもどす  →  取=と, 戻=もど
大人しい / おとなしい  →  大人=おとな                  backtracks past 大=お
真っ青  / まっさお    →  真=ま, 青=さお
承る    / うけたまわる →  承=うけたまわ                5 morae on one kanji
```

**A kanji run is emitted as one group**, never split per character. Splitting
今日 into 今→きょ 日→う would be a fabrication; the reading belongs to the
lexical unit. This is group ruby (グループルビ) and is typographically standard.

99.5 % of the lexicon aligns. The failures are genuinely irregular
colloquial spellings (`こう言う / こーゆー`, `詰らない / つまらねー`) and are
rejected rather than mis-aligned.

## 3. Conjugation

A rule keyed on the dictionary form 書く never fires on 書きました. Exploding
every inflected form would multiply the rule set by ~20. Instead the compiler
exploits the fact that **the reading of the kanji does not change under
inflection**, and keys rules on the invariant stem plus one following character:

| POS | dictionary form | rules generated |
|---|---|---|
| `v5k` | 書く | 書か 書き 書く 書け 書こ 書い — 6 |
| `v1` (kana stem) | 食べる | 食べ — 1 |
| `v1` (kanji stem) | 見る | 見る 見た 見て 見な 見ま 見れ 見よ 見ら 見ろ 見ず 見さ — 11 |
| `adj-i` | 新しい | 新し — 1 |
| `vs` noun | 勉強 | 勉強し 勉強す 勉強さ 勉強せ — 4 |

The rule's input stops at the first inflecting character, so whatever follows
(ました / なかった / られる) is plain kana needing no ruby. 66,716 stem rules
and 45,883 suru-noun rules cover the entire inflectional space.

The ending sets have to be exact. `ICHIDAN_NEXT` originally included い, which
made 着る collide with 着く and produced 着い → きい instead of つい.

Verbs whose kanji reading *does* change (来る → く / き / こ) get an explicit
form table.

The `vs` noun rules exist for precedence, not coverage: 勉強 alone already
matches inside 勉強しました, but without a 外出し rule the rare noun
外出し (そとだし) is a longer rule and wins longest-match over 外出 + し.

## 4. Resolution — or abstention

There is no ranking. A sequence gets a rule only when everything that could
claim it agrees:

1. If the sequence is a lexicon surface classified `AMBIGUOUS`, nothing may
   claim it — not even a form derived from a different verb.
2. A direct lexical entry for exactly this surface outranks a form derived from
   a longer word (同じ is the adjective おなじ, not 同じる's 連用形 どうじ)…
3. …but only when they do not disagree. When they do and neither is
   structurally preferable (説明し = 説明+し or the noun ときあかし), both lose.
4. Two derived forms that disagree (行っ from 行く and from 行う) both lose.

**Abstention is enforced with block rules.** Dropping a rule is not enough:
難しい is ambiguous, but with nothing covering it the 難 rule matched and printed
なん. A block rule matches the sequence and substitutes nothing, consuming the
span so no shorter rule fires.

Full policy, and the four bugs the error corpus exposed, in
[safety.md](safety.md).

### Rule length beats everything

Longest match is implemented as rule order inside a `ChainSubRuleSet`, so a
longer rule always wins. Entries that are just "common word + particle" have to
be **dropped**: as long as a 今日は rule exists it beats 今日, and 今日は６月…
gets こんにちは. No amount of down-ranking helps, because there is no ranking at
match time.

## 5. Reusable ruby glyphs

This is the load-bearing idea. A ruby glyph is identified by

```
(kana character, size, x offset on a 1/20-em grid)
```

and nothing else — never by the word it appears in. 300,364 rules need
**14,194 ruby glyphs across 81 kana and 3 sizes**, and the inventory
*saturates*: 100k rules need 12,591, 300k need 14,194.

The alternative — one composite glyph per word — needs 300,364 glyphs, 4.6× the
65,535 limit. That is the whole reason this architecture exists.

Phase 1 computed the offset with a closed-form quarter-em formula, which is why
its ruby could not be distributed. Phase 2 computes it in
[`layout.py`](typography.md) and quantises the result; the grid is the knob that
trades typography against inventory size.

Each variant is a nested composite (see
[opentype-notes.md](opentype-notes.md#4-nested-composites-dodge-the-scaled_component_offset-ambiguity)),
zero-advance, with `lsb == xMin`.

## 6. GSUB layout

```
ccmp  →  Lookup C          ChainContextSubst fmt 1, 134 subtables, 300,364 rules
         Lookup M0..M1374  MultipleSubst: base glyph → [ruby…, base glyph]
                           (a BLOCK rule maps it to [base glyph] alone)
vert  →  Lookup V          SingleSubst: ruby → blank, + base punctuation forms
vrt2  →  Lookup V
```

- **One `SequenceLookupRecord` per rule**, always at index 0. See
  [opentype-notes.md §2](opentype-notes.md#2-two-glyph-inserting-lookup-records-in-one-context-rule-are-not-portable).
- **Whole word is input**, so the match is consumed and scanning resumes past
  it.
- **Subtables are packed by first glyph**, never splitting a first glyph's rule
  set, with a 48 kB budget to stay inside `Offset16` reach.
- **MultipleSubst lookups are bin-packed.** A subtable is a map keyed by glyph,
  so it holds one output per glyph; the number of lookups needed is exactly
  `max over glyphs of (distinct outputs)`. For the core lexicon that is 1,375 —
  and it is the binding scaling constraint: adding JMnedict pushes it to 8,547,
  past the `LookupList` `Offset16` ceiling, and the font stops compiling
  (see [limitations.md](limitations.md)).

Registered under `DFLT`, `hani`, `kana` and `latn` so script selection cannot
miss it.

## 7. Reference matcher

`engine.py` reimplements the shaping semantics in Python — scan left to right,
try rules for the current character longest-first, jump past the match. It has
two modes:

- `apply` — HarfBuzz and CoreText
- `apply_segmented` — Blink, shaping each maximal script run alone

This lets reading accuracy be measured over 20,000 sentences without building a
font, and lets the shaping tests assert the real font agrees with the reference.
The Blink mode was validated against Chrome 151: every prediction matched.

## 8. Evaluation

`scripts/evaluate.py` scores against UniDic on a held-out split (sentences
0–20,000; priors trained on 20,000–150,000). Match spans and tokeniser tokens
do not have to agree one-to-one — 誕生日 as one rule versus 誕生 + 日 as two
tokens is not an error — so a span is scored whenever it aligns to token
boundaries, and sub-token spans are scored against the token's own okurigana
alignment.

The headline metric is **precision**: of the readings YomiFont actually renders,
how many are right. Coverage is reported separately and is allowed to be low.

Disagreements are split into genuine errors and oracle conventions — the oracle
picked a different reading of the same lexeme (明日 = あした vs あす), or its
tokenizer split a word and concatenated per-token readings, losing rendaku
(日曜日 → にちようひ). Both a strict and a convention-adjusted precision are
reported so the assumption is visible.

`--segmentation script` runs the same evaluation through the Blink model.
