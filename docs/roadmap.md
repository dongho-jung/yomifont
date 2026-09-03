# Roadmap toward broad Japanese coverage

Ordered by value per unit of work, based on what the measurements say is
actually limiting. Items marked **wall** are not on this list by design — see
[limitations.md](limitations.md).

## 1. Vertical writing (largest correctness gap)

Ruby placement is baked in as horizontal offsets, so tategaki currently renders
with furigana suppressed. The fix is mechanical: a second glyph inventory
`rv.<cp>.t<t>` with the offset applied on the vertical axis, selected by
`vert`/`vrt2` instead of the blanking lookup already there. Roughly doubles the
ruby glyph count (3,262 → ~6,500), still far under any limit.

## 2. Merge into the base font's GSUB

YomiFont replaces GSUB wholesale, dropping `locl`, `jp78/83/90`, `nlck` and the
width features. Appending YomiFont's lookups to the existing `LookupList` and
adding a `ccmp` FeatureRecord preserves them. The fiddly part is that
FeatureRecords must stay alphabetically ordered, so existing `FeatureIndex`
references need remapping.

## 3. Size

11.3 MB is too large for the web; the 50k-rule build (2.2 MB) is the practical
one today. Untried compression, in order of expected return:

- **Suffix sharing across ChainSubRules.** 74,358 four-character and 42,208
  five-character rules share long tails; a trie-style factoring of each
  `ChainSubRuleSet` should cut GSUB substantially.
- **Drop rules that can never fire.** A rule is dead if a shorter rule with the
  same reading already covers every context it could match.
- **`woff2`** for web delivery (brotli over a table this repetitive should do
  well; not measured).

## 4. Beyond 300k rules

HarfBuzz's repacker fails between an 8.7 MB and 9.2 MB GSUB and fontTools'
fallback is 4.5x slower. Splitting the rule set across two `ccmp` lookups (both
in the same feature, partitioned so no first glyph appears in both) would keep
each under the repacker's ceiling — but note that two lookups mean two passes
over the buffer, so the partition must guarantee no glyph is reachable by both
or a word could receive ruby twice.

## 5. Coverage the data can still give

- **JMnedict** for place names — fixes 新宿 → しんやど. Adds ambiguity for
  person names, so it should probably be place-names-only, or a separate build.
- **A larger prior corpus.** Priors currently come from 130k Tatoeba sentences.
  Wikipedia would give better frequency estimates for the long tail, where the
  25-observation threshold currently falls back to JMdict.
- **Counter and numeral handling.** `６時` → ろくじ works, but `一日` is
  ついたち or いちにち by context and `1２時` style mixed digits are unhandled.

## 6. Distribution

- Bold and other weights (the base is a variable font; instancing at other
  weights is one line, but the ruby scale may want optical compensation).
- A `.otf`/CFF build. CFF2 has no general composite mechanism, so the ruby
  variants would need charstring subroutines rather than nested composites.
- `woff2` builds and a demo page.

## 7. Explicit reading overrides (optional, researched but not built)

For inherently ambiguous words, a variation-selector mechanism modelled on the
Taiwanese Bopomofo IVS ecosystem could let an author pin a reading:
`人気` + VS1 → にんき, VS2 → ひとけ. This is expressible today — a
ChainContextSubst matching the base glyph plus the variation selector glyph,
with the selector mapping to a zero-width glyph.

It was deliberately not built: it requires the author to edit the text, which
is the thing this project exists to avoid, and the default experience must not
depend on it. It is worth revisiting only as an escape hatch for the 1,194
genuine ties.
