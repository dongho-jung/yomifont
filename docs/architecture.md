# Architecture

```
JMdict_e.gz
    │  jmdict.py        parse, drop everything that cannot affect a reading
    ▼
lexical IR            (surface, reading, priority, POS, flags)   217,489 pairs
    │  alignment.py     okurigana alignment -> ruby groups        99.95 % align
    │  conjugation.py   invariant stems + ending sets
    │  rules.py         conflict resolution, priority, overrides
    ▼
rule set              (seq, groups, priority)                    318,808 rules
    │  rubyglyphs.py    reusable positional ruby glyph inventory   3,262 glyphs
    │  gsub.py          ChainContextSubst + MultipleSubst packing
    │  build.py         subset base font, metrics, naming
    ▼
YomiFont-Regular.ttf   11.3 MB, 9,275 glyphs, no GPOS
```

Everything in this pipeline is ordinary deterministic code. The only
hand-authored data is `data/overrides.tsv` — 14 lines, each with a stated
reason.

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
  `ichi1 + news1 + nf02` because the newspaper corpus is full of 今日は and
  formal 今日的. Reading rank is weighted at 400/200-per-rank, above any
  priority-tag total.

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

99.95 % of the lexicon aligns. The 109 failures are genuinely irregular
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
(ました / なかった / られる) is plain kana needing no ruby. 71,796 stem rules
and 48,019 suru-noun rules cover the entire inflectional space.

The ending sets have to be exact. `ICHIDAN_NEXT` originally included い, which
made 着る collide with 着く and produced 着い → きい instead of つい.

Verbs whose kanji reading *does* change (来る → く / き / こ) get an explicit
form table.

The `vs` noun rules exist for precedence, not coverage: 勉強 alone already
matches inside 勉強しました, but without a 外出し rule the rare noun
外出し (そとだし) is a longer rule and wins longest-match over 外出 + し.

## 4. Conflict resolution

Three tiers, in increasing authority:

1. **JMdict priority** — `ke_pri`/`re_pri` tags plus reading prominence.
2. **Corpus frequency** (optional) — counts from UniDic over a training split,
   at both surface level (中 → なか vs うち) and lemma level (行く/いく vs
   行う/おこなう, which is what ranks the *stem* rules derived from them).
   Corpus evidence forms a **tier above** JMdict priority rather than a bonus
   added to it: a bounded bonus can never separate two readings that both max
   it out. Below 25 observations it degrades to a bounded bonus, because 山道
   is attested さんどう 10 times and やまみち zero, yet JMdict ranks やまみち
   far higher and is right — that count is a tokeniser convention, not usage.
3. **Explicit overrides** — `data/overrides.tsv`, 14 entries, each with a
   stated reason. Mostly UniDic lexeme conventions (私 → ワタクシ,
   日本 → ニッポン) that are correct as lemma readings and wrong as furigana.

Overrides can only *select among readings JMdict already attests*; they can
never introduce one.

### Rule length beats priority

Longest match is implemented as rule order inside a `ChainSubRuleSet`, so a
longer rule always wins regardless of priority. Consequently, entries that are
just "common word + particle" have to be **dropped**, not demoted: as long as a
今日は rule exists it beats 今日, and 今日は６月… gets こんにちは. 249 such
entries are removed.

## 5. Reusable ruby glyphs

This is the load-bearing idea. Placing the *i*-th ruby kana of a reading is
pure arithmetic:

```
x_i = group_start·EM + (span·EM − n_kana·RUBY_ADV)/2 + i·RUBY_ADV
    = 250 · (4·group_start + 2·span − n_kana + 2·i)
    = 250 · t
```

So a ruby glyph is identified by `(kana, t)` and nothing else — not by the word
it appears in. 318,798 rules need **3,262 ruby glyphs across 81 kana**, about
40 positional variants each, and the inventory *saturates*: 100k rules need
3,109, 318k need 3,262.

The alternative — one composite glyph per word — needs 318,798 glyphs, 4.9× the
65,535 limit. That is the whole reason this architecture exists.

Each variant is a nested composite (see
[opentype-notes.md](opentype-notes.md#4-nested-composites-dodge-the-scaled_component_offset-ambiguity)),
zero-advance, with `lsb == xMin`.

## 6. GSUB layout

```
ccmp  →  Lookup C     ChainContextSubst fmt 1, 141 subtables, 318,798 rules
         Lookup M0..M1444   MultipleSubst: base glyph → [ruby…, base glyph]
vert  →  Lookup V     SingleSubst: ruby → blank, plus base punctuation forms
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
  `max over glyphs of (distinct outputs)`. For the full lexicon that is 1,445.

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

The headline metric is **token-level**: of all kanji-bearing tokens, how many
got a correct reading. Span-level accuracy alone is misleading, because adding
a fallback rule moves tokens from "no ruby" (unscored) into "scored", lowering
span accuracy while making the font strictly more useful.

Disagreements are split three ways: a different **attested** reading, a reading
**not attested** for that word (a real defect, 0.36 % of spans), and a
**deliberate override**.
