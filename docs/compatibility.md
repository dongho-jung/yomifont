# Compatibility

Reproduce with:

```bash
make test                                   # HarfBuzz + CoreText, 214 assertions
./tests/integration/server.py &             # serve the repo
open http://127.0.0.1:8777/tests/integration/engine_probe.html   # in each browser
./tests/integration/compare_engines.py      # compare against a HarfBuzz reference
```

## Summary

| engine | GSUB runs | readings correct | abstentions honoured | coverage | explicit ruby | notes |
|---|---|---|---|---|---|---|
| HarfBuzz 14.2.1 (`hb-shape`, `uharfbuzz`) | yes | 99.94 % | yes | 79.1 % | all cases | reference |
| CoreText (macOS 26.5, `tools/ctshape`) | yes | identical glyph stream to HarfBuzz | yes | 79.1 % | all cases | |
| Safari 26.6 / WebKit | yes | **16/16 probe cases match HarfBuzz exactly** | yes | 79.1 % | **18/18** | |
| Chrome 152 / Blink | yes, but script-segmented | 99.87 % | yes | **48.9 %** | **6/18, kana bases only** | |
| Firefox | not tested (not installed) | | | | | |
| DirectWrite / Windows | not tested (no Windows host) | | | | | |
| Word / LibreOffice / Adobe | not tested | | | | | |

Untested rows are untested, not "probably fine".

Explicit ruby is measured separately by `explicit_probe.html`; the per-case
results and the reason Blink can only manage kana bases are in
[explicit-ruby.md](explicit-ruby.md).

## Resolved: the Chrome 152 "Phase 2 renders no ruby" issue

This was a **defect in the probe, not in Chrome or the font.**

The finding reproduces exactly and reliably: in headless Chrome 152, the canvas
probe measures 2,674 ink pixels above the em box for 東京 with the Phase 1 font
and **0** with the Phase 2 font, with identical base-text ink (6,493 px in
both). Removing `vert`/`vrt2`, removing the imported heavier-weight ruby
outlines, and giving the ruby glyphs a non-zero advance all leave it at 0.

It is a **canvas-path** artifact. Chrome's canvas 2D text pipeline does not
apply `ccmp` for these fonts; its DOM pipeline does. Rendering the same strings
in the DOM and screenshotting shows Phase 2 ruby drawing correctly and
identically to Phase 1:

```bash
./tests/integration/server.py &
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
  --screenshot=/tmp/domtest.png --window-size=1400,700 \
  http://127.0.0.1:8777/tests/integration/domtest.html
```

Two further checks separate the layers:

* `raster_probe.html` (font from `make_raster_font.py`) maps ruby-style
  composites straight into `cmap`, so no shaping is involved. Chrome draws
  **all** of them — one-level and two-level composites, at y=900 and y=940, and
  at an x offset of −6,900 units. So rasterisation was never the problem.
* `explicit_probe.html` measures the DOM inline-box width, and Chrome collapses
  it exactly as expected wherever the run is not script-split. So GSUB is
  applied in the DOM path.

**Chrome 152 renders the Phase 2 font correctly.** `engine_probe.html`'s
canvas-based ink signature under-reports it and should not be used to judge
Chrome; use the DOM screenshot or the width measurement instead.

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

## Exactly where Blink starts a new shaping run

Measured, not inferred from Unicode properties. `make_itemize_font.py` builds a
font carrying one GSUB rule per candidate character sequence; each rule blanks
the sequence's *first* glyph, so the text is one em narrower **iff the whole
sequence reached GSUB in a single run**. Every character used is in the probe
font, so a split is never font fallback, and `itemize_probe.html` reads two
independent channels (DOM inline width and canvas ink extent) because Chrome
and WebKit are each unreliable on one of them.

```bash
PYTHONPATH=src ./tests/integration/make_itemize_font.py dist/Itemize.ttf
./tests/integration/server.py &
open http://127.0.0.1:8777/tests/integration/itemize_probe.html
```

153 sequences, 30 separator characters. Chrome 152:

| transition | result |
|---|---|
| Han → Han | SAME_RUN |
| Han → **digit** | **SAME_RUN** |
| Han → Hiragana | SPLIT |
| Han → Katakana | SPLIT |
| Han → Latin | SPLIT |
| Hiragana → Han | SPLIT |
| Katakana → Han | SPLIT |
| Hiragana ↔ Katakana | SAME_RUN |

And with a separator between Han and Kana — **all 28 split**, in both
directions, including every invisible one:

```
｜ | （ ( ： : ／ / ［ [ ｛ ＜ 、 ・ ー 　 space _
U+200B ZWSP   U+200C ZWNJ   U+200D ZWJ   U+2060 WORD JOINER
U+034F CGJ    U+FE00 VS1    U+FE0E VS15
U+E000 PUA    U+F8FF PUA
```

The control that makes this conclusive: the same separators between two *kana*
are SAME_RUN (ZWSP, ZWJ, WJ, CGJ, VS1, VS15 all pass), so those characters do
reach GSUB and do participate in matching. Their Han↔Kana split is a real run
boundary, not the character being stripped. Two exceptions, both informative:
**U+200C ZWNJ splits even between two kana**, and **PUA splits from everything**
— a PUA character measured 16 px, our own probe glyph, so that is a genuine run
boundary and not fallback.

So the rule is not "special characters break runs". Common-script characters
*join* the Han run — that is why `Han → digit` stays together and why the
prefix `｜月（` is one run. What Blink will not do is put Han and Kana in the
same run, whatever sits between them.

**Consequence for explicit ruby.** No character encoding of the syntax can
work in Blink — not punctuation, not joiners, not variation selectors, not PUA.
The font can still see the *prefix* `｜BASE（`, which is what the fail-safe in
[explicit-ruby.md](explicit-ruby.md) uses.

One measured asymmetry between the two syntaxes, the first found: the
fullwidth prefix `｜月（` is SAME_RUN, the ASCII prefix `|月(` is SPLIT. The
fail-safe therefore only works for the fullwidth form.

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
