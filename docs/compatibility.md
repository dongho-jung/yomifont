# Compatibility

Everything here is reproducible:

```bash
make test                                   # HarfBuzz + CoreText, 194 assertions
./tests/integration/server.py &             # serve the repo
open http://127.0.0.1:8777/tests/integration/engine_probe.html   # in each browser
./tests/integration/compare_engines.py      # compare against a HarfBuzz reference
```

## Summary

| engine | via | GSUB runs | ruby appears | correct across Han↔Kana | clipping | line height | copy/paste |
|---|---|---|---|---|---|---|---|
| HarfBuzz 14.2.1 | `hb-shape`, `uharfbuzz` | yes | yes | yes | n/a | n/a | n/a |
| CoreText (macOS 26.5) | `tools/ctshape` | yes | yes | yes | none | ok | n/a |
| Safari 26.5 (WebKit) | browser probe | yes | yes | **yes** | none | 1.62 em | text unchanged |
| Chrome 151 (Blink) | browser probe | yes | yes | **only via mitigation** | none | 1.62 em | text unchanged |
| Firefox | — | not tested (not installed) | | | | | |
| DirectWrite / Windows | — | not tested (no Windows host) | | | | | |
| LibreOffice / Word / Adobe | — | not tested | | | | | |

Untested rows are untested. They are not "probably fine".

## What was measured

**Glyph-stream equality.** `tests/shaping/test_shaping.py` shapes every corpus
case with both `uharfbuzz` and CoreText and asserts the glyph names and
advances are *identical*. 194 assertions, all passing.

**Browser rendering.** `engine_probe.html` renders each test string to a canvas
and reports a column-occupancy bitmap of everything drawn above the em box.
`compare_engines.py` builds the expected bitmap from glyph geometry — shape with
HarfBuzz, look up each ruby glyph's `glyf` bounding box, mark the em-columns it
covers — so the reference is exact and rasterizer-independent.

Result after the Blink mitigation: **every engine draws the same ruby glyphs as
HarfBuzz** on all 14 probe strings. Chrome scores 90–100 % bucket agreement
(the shortfall is antialiasing spill; the glyphs are the same), Safari 100 %.

**Page-level invariants** (`compat.html`, Chrome and Safari):

```
PASS  font loads (@font-face, document.fonts.check)
PASS  textContent unchanged: "銀行へ行った。"
PASS  Range.toString() unchanged: "銀行へ行った。"
PASS  advance width unchanged by ruby: 1200.0 vs 1200.0
PASS  12 full-width chars at 100px = 1200px, measured 1200.0
PASS  line box 48.5px for 30px text (needs >= 45 for ruby)
```

The width check compares YomiFont against *itself* with `font-feature-settings:
"ccmp" 0`, which isolates the effect of ruby from any font-metric difference.

**Validation.** OpenType Sanitizer — the validator Chrome and Firefox run web
fonts through before using them — passes at every scale from 1,000 to 318,798
rules.

---

## The Blink finding

Blink itemises a text node into script runs *before* shaping, so **no GSUB rule
can match across a Han↔Kana boundary in Chrome**. `行った` is shaped as `行`
plus `った`; the okurigana that identifies the verb is in a different shaping
call and simply is not visible to the lookup.

This was confirmed by prediction, not inference: for every test string, Chrome's
output is exactly what HarfBuzz produces when each maximal Han run is shaped
alone. `engine.py:apply_segmented` implements that model and reproduces Chrome.

CoreText does not segment this way, so Safari and native macOS controls are
unaffected.

### Cost and mitigation, measured

20,000 held-out Tatoeba sentences, 79,321 kanji-bearing tokens. "correct" =
the token received ruby with the reading UniDic assigns in context.

| rule set | engine model | correct | wrong | no ruby |
|---|---|---|---|---|
| JMdict only | HarfBuzz / CoreText | 91.16 % | 5.45 % | 0.15 % |
| JMdict only | Blink | 69.82 % | 20.32 % | 8.22 % |
| + UniDic priors + overrides | HarfBuzz / CoreText | **92.60 %** | 4.11 % | 0.04 % |
| + UniDic priors + overrides | Blink | 71.36 % | 19.25 % | 7.75 % |
| + lone-kanji fallbacks | HarfBuzz / CoreText | 92.13 % | 4.60 % | 0.03 % |
| + lone-kanji fallbacks | Blink | **91.31 %** | 6.80 % | 0.24 % |

Script segmentation costs **21.2 points**. The lone-kanji fallback recovers
**19.9** of them, for **0.5 points** given up in non-segmenting engines. It is
on by default; `--no-lone-kanji` disables it.

### How the mitigation works

For each kanji, the single-character rule's reading is taken from how that
kanji is actually read when it stands alone between kana, counted over the
training corpus using the same okurigana alignment the compiler uses:

```
行  →  い 3868   おこな 354   ぎょう 25
分  →  わ  622   ぶん   313   ふん  271
新  →  あたら 942  しん 133    あら   39
```

604 rules are affected (291 kanji gained a fallback that had none, 313 changed).
The reading is never invented: it must already be one YomiFont assigns to that
character in another rule.

### What remains broken in Blink

Okurigana cannot disambiguate, so `行く` and `行う` both get い. Any distinction
that lives in the kana is unavailable. All-Han words are unaffected — longest
match works normally there, verified on 大人→おとな, 明日→あした,
一昨日→おととい, 八百屋→やおや, 日本語→にほんご.

---

## Line height and clipping

Ruby sits at y = 900 with ink to about y = 1320 (em = 1000). Vertical metrics
are set to ascent 1330 / descent −288 with `USE_TYPO_METRICS`, giving a 1.62 em
default line box. No clipping was observed in Chrome or Safari at
`line-height: normal`; consecutive lines do not overlap.

If a host application overrides line height below ~1.4 em, ruby will collide
with the line above. That is a property of the metrics, not a bug that can be
fixed in the font.

## Text integrity

Shaping never modifies the character buffer, so this is structural rather than
best-effort: `textContent` and `Range.toString()` return the original string,
cluster values map every ruby glyph back to its source character index, and
total advance width is identical with and without ruby.
