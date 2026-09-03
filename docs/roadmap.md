# Roadmap

Ordered by what the measurements say is actually limiting. Items marked **wall**
are excluded by design — see [limitations.md](limitations.md).

## 1. Resolve the Chrome 152 regression (blocking)

One controlled measurement showed Chrome rendering no ruby with the Phase 2
font while rendering it correctly with the Phase 1 font; it was not reproduced
before the probe stopped reporting. Until this is settled, Chrome support is
unverified. `engine_probe.html?font=<path>` is the bisection harness; the
candidates are the three-size ruby inventory, the outlines imported from a
second weight instance, and the raised ascent.

## 2. Two-lookup partition, to make the names build compile

The JMnedict build needs 8,547 MultipleSubst lookups against a ~3,000 ceiling.
Splitting the rule set across two `ccmp` lookups halves the pressure, but the
partition must guarantee no first glyph appears in both — otherwise the second
pass fires on a word the first already handled and it gets ruby twice. Partition
by first glyph and the guarantee is structural.

## 3. Recover coverage safely

Coverage is 79 % (49 % in Blink) and every point of it was given up for a
measured reason. The ones worth revisiting:

- **Single-kanji rules with a script-run guard.** Dropping them cost 4.4 points.
  A ChainContextSubst format 3 rule with a non-kanji lookahead would restore
  them for kanji that are not inside a compound, at the price of failing at the
  start of a shaping run. Worth measuring rather than assuming.
- **A larger corpus for the evaluation**, so rare words are actually exercised;
  Tatoeba is conversational and barely touches proper nouns (365 name tokens in
  20,000 sentences).
- **Sense-restricted readings.** JMdict's `stagr` says which senses a reading
  covers; a reading that covers *every* sense of its entry is safer than one
  restricted to a single sense. Currently unused.

## 4. Typography

- **Mono-ruby and jukugo-ruby** for compounds where per-character readings are
  derivable.
- **Per-kana optical spacing** — う, し, っ and the small kana read lighter than
  their boxes suggest.
- **Vertical writing**: a second inventory with the offset on the vertical axis,
  selected by `vert`/`vrt2` instead of the current blanking lookup. Roughly
  doubles the ruby glyph count, still far inside the limit.
- **Ruby-specific outlines.** Weight compensation is applied; the shapes are
  still the text kana.

## 5. Size

11.2 MB, and the finer placement grid means even a 60k-rule build is 3.7 MB.
Untried, in order of expected return: suffix sharing across `ChainSubRule`s
(94,557 three-character and 72,422 four-character rules share long tails);
dropping rules a shorter rule already covers identically; `woff2`.

## 6. Merge into the base font's GSUB

YomiFont replaces GSUB wholesale, dropping `locl`, `jp78/83/90`, `nlck` and the
width features. Appending to the existing `LookupList` preserves them; the
fiddly part is that `FeatureRecord`s must stay alphabetically ordered, so
existing `FeatureIndex` references need remapping.

## 7. Distribution

Bold and other weights (the base is variable, but the ruby scale may want
optical compensation per weight), a CFF build (CFF2 has no general composite
mechanism, so ruby variants would need charstring subroutines), `woff2`, and a
demo page.

## Not on this list

**wall** — readings that depend on sentence meaning, person-name readings, and
okurigana context under Blink. See [limitations.md](limitations.md).
