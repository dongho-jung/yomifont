# Chromium bug report — draft

Filed against **`Chromium > Blink > Fonts`** (component id 1456925, from
`third_party/blink/renderer/platform/fonts/DIR_METADATA`).

The form has a **Markdown** checkbox under the Description box. Tick it, or the
tables below arrive as one run-on paragraph.

The repro is given as source rather than an attachment: it asks a stranger for
two minutes instead of for trust, and it is auditable at a glance.

Two parts on purpose. The **Description** is the bug: repro, expected, actual,
environment. The **first comment** is the analysis and the suggested fix. A
reporter who has already decided what the fix should be reads as someone who
has not really looked, and an owner who only wants to know whether the bug is
real should not have to scroll past a proposal to find out.

---

## Title

```
GPOS kerning is not applied across Han–Kana boundaries within the same font
```
---

## Description — paste this

Chrome does not apply GPOS pair kerning across Han–Hiragana or Han–Katakana
boundaries, even when both characters come from the same font and
`font-kerning: normal` is explicitly set. The test below defines eight kerning
pairs: the four control pairs are applied, the four Han–Kana pairs are not.

Safari applies all eight with the same font.

### Steps to reproduce

I found no Han–Kana kern pair in the three fonts I inspected — Hiragino Kaku
Gothic W3, Hiragino Mincho ProN and Noto Sans JP, which have 5,982 CJK pairs
between them — so the case needs a font built for it. These two files build one
from any Japanese font you already have.

`build.py`

```python
import sys
from fontTools.ttLib import TTFont
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString

PAIRS = ["漢字", "あい", "アイ", "あア", "漢あ", "あ漢", "漢ア", "ア漢"]

font = TTFont(sys.argv[1], fontNumber=0)
cmap = font.getBestCmap()
kern = -round(font["head"].unitsPerEm / 2)
features = """
languagesystem DFLT dflt;
languagesystem hani dflt;
languagesystem kana dflt;
feature kern {
""" + "".join(
    f"  pos {cmap[ord(a)]} {cmap[ord(b)]} {kern};\n"
    for a, b in PAIRS
) + "} kern;\n"

# Replaces the font's OpenType layout with just this feature.
addOpenTypeFeaturesFromString(font, features)
font.save("kernprobe.ttf")
print(f"Expected reduction at 100px: {-kern / font['head'].unitsPerEm * 100:.2f}px")
```

`probe.html`, in the same directory

```html
<!doctype html>
<html lang="ja">
<meta charset="utf-8">
<title>Han-Kana GPOS kerning test</title>
<style>
@font-face { font-family: K; src: url(kernprobe.ttf); }
#stage { position: absolute; visibility: hidden; }
#probe { font: 100px K; white-space: nowrap; letter-spacing: 0; word-spacing: 0; }
</style>
<div id="stage"><span id="probe"></span></div>
<pre id="out">Loading test font…</pre>
<script>
// Two channels, reported separately. Each browser responds on only one of them
// -- the control pairs, which are inside a single script run by construction,
// show which channel to read.
const pairs = ["漢字", "あい", "アイ", "あア", "漢あ", "あ漢", "漢ア", "ア漢"];
const probe = document.getElementById("probe");
const out = document.getElementById("out");
const ctx = document.createElement("canvas").getContext("2d");

const dom = (text, kerning) => {
  probe.style.fontKerning = kerning;
  probe.textContent = text;
  return probe.getBoundingClientRect().width;
};
const canvas = (text, kerning) => {
  ctx.font = "100px K";
  if ("fontKerning" in ctx) ctx.fontKerning = kerning;
  return ctx.measureText(text).width;
};

(async () => {
  const faces = await document.fonts.load("100px K", pairs.join(""));
  await document.fonts.ready;
  if (!faces.length) throw new Error("Test font was not loaded");

  // Reported per channel, not combined: they measure differently and each
  // browser responds on only one of them. The control rows say which.
  out.textContent = "pair  DOM none/normal   canvas none/normal\n" + pairs.map(t =>
    `${t}  ${dom(t, "none").toFixed(0).padStart(4)}/${dom(t, "normal").toFixed(0).padEnd(11)}`
    + `${canvas(t, "none").toFixed(0).padStart(4)}/${canvas(t, "normal").toFixed(0)}`
  ).join("\n");
})().catch(e => { out.textContent = `ERROR: ${e.message}`; });
</script>
</html>
```

```sh
python3 -m pip install fonttools
python3 build.py /path/to/NotoSansJP-Regular.ttf
open probe.html
```

The generated font has a single GPOS `kern` feature with those eight pair
adjustments, registered under `DFLT`, `hani` and `kana`, and no GSUB table at
all. Each adjustment is −0.5 em — for Noto Sans JP, exactly −500 units at 1000
upem, so 50 px at a font size of 100 px.

The page measures the same string in the same span twice, with
`font-kerning: none` and `font-kerning: normal`, so nothing but kerning differs
between the two measurements.

### Expected

All eight pairs are reduced by 50 px.

### Actual

Chrome 152.0.7977.76 and Safari 26.6.2, macOS 26.6.2. Widths in px at 100 px
font size, `font-kerning: none` / `normal`:

| pair | transition | Chrome DOM | Chrome canvas | Safari DOM | Safari canvas |
|---|---|---|---|---|---|
| 漢字 | Han → Han *(control)* | 200 / **150** | 200 / 200 | 200 / 200 | **150 / 150** |
| あい | Hira → Hira *(control)* | 200 / **150** | 200 / 200 | 200 / 200 | **150 / 150** |
| アイ | Kata → Kata *(control)* | 200 / **150** | 200 / 200 | 200 / 200 | **150 / 150** |
| あア | Hira → Kata *(control)* | 200 / **150** | 200 / 200 | 200 / 200 | **150 / 150** |
| **漢あ** | **Han → Hira** | **200 / 200** | 200 / 200 | 200 / 200 | **150 / 150** |
| **あ漢** | **Hira → Han** | **200 / 200** | 200 / 200 | 200 / 200 | **150 / 150** |
| **漢ア** | **Han → Kata** | **200 / 200** | 200 / 200 | 200 / 200 | **150 / 150** |
| **ア漢** | **Kata → Han** | **200 / 200** | 200 / 200 | 200 / 200 | **150 / 150** |

The four control pairs sit inside a single script run by construction, so they
show which channel is meaningful in each browser. In Chrome only the DOM
channel responds — its canvas reports 200 for every pair, controls included. In
Safari it is the other way round: its DOM reports 200 for every pair, controls
included, and its canvas reports 150 for every pair. What these measurements
show is which channel isolates the effect; they do not by themselves establish
why the other channel does not.

Reading each browser on the channel where its controls respond: **漢あ is
kerned in Safari and is not kerned in Chrome**, while the control 漢字 is
kerned in both.

### Shaping the same font outside a browser

| shaper | version | result |
|---|---|---|
| CoreText, one call per pair | macOS 26.6.2 | all eight pairs kerned |
| HarfBuzz, whole pair in one buffer | 14.4.0 | all eight pairs kerned |

The HarfBuzz row is a check that the font's lookups are well formed — it hands
the shaper both characters in one buffer, which is the thing under discussion,
so it says nothing about where a browser ought to split. CoreText is doing its
own segmentation, and it is what WebKit shapes with on macOS.

This prevents font-defined pair kerning across Han–Kana boundaries in Japanese
text — including between a kanji and its okurigana — with no font change, no
style change and no element boundary involved.

### Environment

- Chrome 152.0.7977.76
- macOS 26.6.2
- Windows and Linux: not tested

I have some notes on where this comes from and on whether changing it could be
made safe. Adding them as a comment rather than inline here.

## First comment — paste this after filing

### Where the boundary comes from

`RunSegmenter` splits the text into script runs before shaping, and
`HarfBuzzShaper::Shape` shapes each segment independently:

```cpp
for (const RunSegmenter::RunSegmenterRange& segmented_range : ranges) {
  ShapeSegment(&range_data, segmented_range, result);
}
```

Font fallback happens inside `ShapeSegment`, and `RunSegmenter`'s constructor
takes only a text buffer and a `FontOrientation`, so the split is decided from
the text alone before any font is consulted. That is also why no font can work
around it: I tried thirty separators between a kanji and a kana, including
U+200B ZWSP, U+200D ZWJ, U+2060 WORD JOINER, U+034F CGJ, U+FE00/U+FE0E
variation selectors and PUA, and all thirty split. The same separators between
two *kana* do not split, which shows they do reach shaping and participate in
matching — so this is a run boundary rather than the character being dropped.

### Blink already merges one such pair on purpose

`script_run_iterator.cc`:

```cpp
// UScriptCode and OpenType script are not 1:1; specifically, both Hiragana and
// Katakana map to 'kana' in OpenType. They will be mapped correctly in
// HarfBuzz, but normalizing earlier helps to reduce splitting runs between
// these scripts.
inline UScriptCode GetScriptForOpenType(UChar32 ch, UErrorCode* status) {
  UScriptCode script = uscript_getScript(ch, status);
  ...
  if (script == USCRIPT_KATAKANA || script == USCRIPT_KATAKANA_OR_HIRAGANA)
    return USCRIPT_HIRAGANA;
  return script;
}
```

That is the あア row, and the stated reason — Unicode script boundaries are not
the boundaries OpenType cares about — reads as though it applies to Han in
Japanese text too.

Separately, `han_kerning.h` says *"OpenType features can't handle kerning at
font boundaries by design."* `HanKerning` exists to emulate spacing the font
cannot supply across a **font** boundary, which is unavoidable. The boundary
here is not.

### Would merging those runs change anything else?

Two things I checked, because they are the obvious objections.

**In the fonts I checked, the script tag makes no difference.** Han maps to
`hani` and Kana to `kana`, so a merge has to pick one. Shaping the same Han+Kana
string with the tag forced to `hani`, `kana` or `DFLT` gave me an identical
glyph stream. Same feature tags is not enough on its own — a tag can point to
different lookups under different scripts — so I compared the resolved lookup
indices, and in these fonts `hani` and `kana` reach the *same* lookups in both
GSUB and GPOS:

| font | feature tags | lookup indices (GSUB / GPOS) |
|---|---|---|
| Hiragino Kaku Gothic W3 | identical | identical |
| Hiragino Mincho ProN | identical | identical |
| Hiragino Sans GB | identical | identical |
| Noto Sans JP | identical | identical |
| Arial Unicode (pan-Unicode, not a JP font) | differ — `locl salt smpl trad` under `hani` only | — |

Four fonts is not a survey, and a font *may* legitimately point the same tag at
different lookups per script. So this is a precondition to check, not something
to assume.

**Neither script has a complex shaper**, so merging does not change which
shaper runs.

What I am *not* claiming is free is font fallback. Today each segment resolves
a font independently; a merged run has to resolve one. That is the real risk.

### A direction that avoids that risk

Not `ScriptRunIterator` — merging there changes which font gets picked, which
is the part that cannot be argued to be safe.

Instead: merge adjacent Han and Kana segments **after fallback has resolved,
and only when both resolved to the same font** — and, since the merged run has
to pick one script tag, only when that font resolves `hani` and `kana` to the
same lookups. That second condition is what makes the merge inert for a font
that does not have a lookup spanning the boundary; without it, "same font" alone
does not guarantee the same features apply. Both conditions are computable once
per font and cacheable.

A cheaper approximation of the same ordering, without restructuring the
fallback loop: resolve only the first fallback font per segment, group adjacent
segments that share it, and let the existing reshape queue handle fallback
inside a group.

I am happy to implement this behind a `base::Feature` and write the layout
test — but I would rather hear
which direction you want first. I have not uploaded a CL.

### A smaller, separable one

`ヶ` U+30F6 and `ヵ` U+30F5 are Katakana by property but are used as
abbreviations of 箇 *inside* Han words: 一ヶ月, 関ヶ原, 霞ヶ関. They therefore
split such a word into three runs. Scoped to two characters, that is much
smaller than the above and independent of it. Happy to file it separately.

### Possibly the same root cause

The duplicate finder surfaced these, and they look like the same mechanism at
different boundaries rather than duplicates of each other:

* "Kerning is not being applied between CJK punctuation and glyphs from
  non-CJK scripts" (P2) — Han→Latin fails the same way in my measurements
* "Ligatures don't work after Korean character" (P3)
* "Ligatures between emoji and non-emoji codepoints are not applied" (P3) —
  the `SymbolsIterator` boundary rather than the script one

*(replace with issue numbers before posting)*

### Where this came from

I maintain a font that renders furigana from GSUB, which is how I found it: a
rule keyed on a kanji plus its okurigana cannot match, so 生きる gets no
reading while an all-kanji word like 東京都新宿区 does. That use case is
unusual and is not the argument — the report above is a plain GPOS pair in a
font with no GSUB at all. Mentioning it so the motivation is on the record.
