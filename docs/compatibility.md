# Compatibility

Reproduce with:

```bash
make test                                   # HarfBuzz + CoreText, 214 assertions
./tests/integration/server.py &             # serve the repo
open http://127.0.0.1:8777/tests/integration/engine_probe.html   # in each browser
./tests/integration/compare_engines.py      # compare against a HarfBuzz reference
```

## Summary

| engine | GSUB runs | readings correct | abstentions honoured | coverage | notes |
|---|---|---|---|---|---|
| HarfBuzz 14.2.1 (`hb-shape`, `uharfbuzz`) | yes | 99.94 % | yes | 79.1 % | reference |
| CoreText (macOS 26.5, `tools/ctshape`) | yes | identical glyph stream to HarfBuzz | yes | 79.1 % | |
| Safari 26.5 / WebKit | yes | **16/16 probe cases match HarfBuzz exactly** | yes | 79.1 % | |
| Chrome 152 / Blink | yes, but script-segmented | 99.87 % | yes | **48.9 %** | **see open issue below** |
| Firefox | not tested (not installed) | | | | |
| DirectWrite / Windows | not tested (no Windows host) | | | | |
| Word / LibreOffice / Adobe | not tested | | | | |

Untested rows are untested, not "probably fine".

## Open issue: Chrome 152 and the Phase 2 font

In one controlled session, the browser probe measured Chrome 152 rendering the
**Phase 1** font's ruby (2,674 ink pixels above the em box for 東京) and the
**Phase 2** font's ruby not at all (0 pixels), with identical base-text
rendering. Removing the block rules did not change it. The Chrome probe then
stopped reporting altogether — including for the Phase 1 font that had worked
minutes earlier — so the cause was never isolated.

What is known:

* Safari 26.5 renders the Phase 2 font correctly on all 16 probe cases.
* HarfBuzz 14.2.1 and CoreText both render it correctly.
* OpenType Sanitizer 9.2.0 passes the font.
* The two fonts are structurally similar (same tables, same `maxp` component
  depth of 2, lsb range well inside int16, `indexToLocFormat` 1 in both).

**Treat Chrome support as unverified for Phase 2 until this is reproduced and
resolved.** The Phase 1 font is known to work in Chrome 151 and 152; the
regression, if it is one, was introduced somewhere in the Phase 2 glyph
inventory (14,194 ruby glyphs across three sizes, outlines imported from a
heavier weight instance) or in the rule set. `?font=` on the probe URL selects
which font to measure, which is the harness for bisecting it.

## What is verified

**Glyph-stream equality.** `tests/shaping/test_shaping.py` shapes every corpus
case with both `uharfbuzz` and CoreText and asserts the glyph names and
advances are identical — 214 assertions, all passing. This includes the
abstention cases: 市場, 人気, 生物, 大人, 人, 時, 中, 強い, 行った, 僕, 大丈夫
must all produce **zero** ruby glyphs.

**Browser rendering.** `engine_probe.html` renders each test string to a canvas
and reports a column-occupancy bitmap of everything above the em box.
`compare_engines.py` builds the expected bitmap from glyph geometry — shape with
HarfBuzz, look up each ruby glyph's `glyf` bounding box, mark the em-columns it
covers — so the reference is exact and rasterizer-independent. Safari matches at
100 % on every case.

**Validation.** OTS passes at every scale from 1,000 to 300,364 rules.

## Blink's script segmentation

Blink itemises a text node into script runs *before* shaping, so no GSUB rule
can match across a Han↔Kana boundary. `行った` is shaped as `行` plus `った`, and
the okurigana that identifies the verb is in a different shaping call.

This was confirmed by prediction in Phase 1: for every test string, Chrome's
output was exactly what HarfBuzz produces when each maximal Han run is shaped
alone. `engine.py:apply_segmented` implements that model and is what the
`--segmentation script` evaluation uses.

CoreText does not segment this way, so Safari and native macOS controls are
unaffected.

### Phase 2 response: abstain, do not guess

Phase 1 recovered Blink coverage by deriving a single-kanji fallback reading
from corpus statistics — it moved Blink from 71 % to 91 % correct tokens, but it
was a guess. Phase 2 removes it. Single-character rules are gone entirely, and
an all-Han rule that is also the stem of an inflecting verb (微笑 = びしょう and
also 微笑む's stem ほほえ) is dropped, because under segmentation nothing can
separate them.

| | HarfBuzz / CoreText | Blink model |
|---|---|---|
| precision | 99.942 % | 99.868 % |
| wrong readings (20k sentences) | 31 | 45 |
| coverage | 79.1 % | 48.9 % |

Chrome gets **half the coverage and the same precision**. That is the intended
trade: engine-specific coverage differences are acceptable, engine-specific
wrong readings are not.

Dropping the segmentation-unsafe prefix rules alone took Blink from 242 wrong
readings to 23 at a cost of 0.65 points of coverage; restoring 日本 and 今日
(which an over-broad version of the same check had deleted) brought it back to
45. The trade was made in that direction deliberately.

## Line height and clipping

Ruby sits at y = 940 and the tallest ruby glyph reaches y = 1373 (em = 1000).
Vertical metrics are ascent 1400 / descent −288 with `USE_TYPO_METRICS`, giving
a **1.688 em** default line box against a **1.455 em** ink span, so consecutive
lines cannot overlap at `line-height: normal`. A host that forces line-height
below ~1.46 em will collide; that is a property of the metrics, not something
the font can prevent.

## Text integrity

Shaping never modifies the character buffer, so this is structural rather than
best-effort. Verified in Chrome and Safari via `compat.html`:

```
PASS  font loads (@font-face, document.fonts.check)
PASS  textContent unchanged: "銀行へ行った。"
PASS  Range.toString() unchanged: "銀行へ行った。"
PASS  advance width unchanged by ruby: 1200.0 vs 1200.0
PASS  12 full-width chars at 100px = 1200px, measured 1200.0
PASS  line box 48.5px for 30px text
```

The width check compares YomiFont against *itself* with
`font-feature-settings: "ccmp" 0`, isolating the effect of ruby from any
font-metric difference.
