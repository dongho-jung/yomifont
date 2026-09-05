# Chromium bug report — draft

Paste-ready for <https://issues.chromium.org>. Component **`Blink>Fonts`**,
type **Bug**, OS **All** (reproduced on macOS; the code path is not
platform-specific). Attach `tests/integration/blink-han-kana-kerning-repro.html`
— one self-contained file, 25 KB, no server and no external resources.

The OWNERS of `third_party/blink/renderer/platform/fonts` are kojii@chromium.org
and tkent@chromium.org. Do not send a Gerrit CL before an owner has said which
direction they want; this is core text-stack behaviour and a CL that arrives
without that agreement will be closed.

Everything below is measured, and each measurement is reproducible from this
repository. Where a number is not measured it says so.

---

## Title

Font kerning is not applied across a Han↔Kana boundary

## Component

`Blink>Fonts`

## Steps to reproduce

1. Save the attached `blink-han-kana-kerning-repro.html` and open it. It needs
   no server; the font is embedded as a data URI.
2. Read the table it prints.

The embedded font is 148 glyphs of Noto Sans JP (OFL 1.1) carrying exactly one
feature: a `kern` pair of −500/1000 em on each script transition in the table.
It has no GSUB. At 100 px that kern is 50 px, so a pair that reached GPOS as a
single run measures 50 px narrower than its two characters measured separately.

## Expected

All ten pairs are kerned. The font declares a `kern` pair for each of them and
`font-kerning: normal` is in effect.

## Actual — Chrome 152.0.7977.76

| pair | transition | kerned |
|---|---|---|
| 漢字 | Han → Han | yes |
| あい | Hiragana → Hiragana | yes |
| アイ | Katakana → Katakana | yes |
| あア | Hiragana → Katakana | yes |
| 漢1 | Han → digit (Common) | yes |
| **漢あ** | **Han → Hiragana** | **no** |
| **あ漢** | **Hiragana → Han** | **no** |
| **漢ア** | **Han → Katakana** | **no** |
| **ア漢** | **Katakana → Han** | **no** |
| **漢A** | **Han → Latin** | **no** |

So a Japanese font cannot adjust the spacing between a kanji and the kana that
follows it — the most common adjacency in the language — in Chrome.

## Other engines

| engine | version | result |
|---|---|---|
| Chrome / Blink | 152.0.7977.76 | **5 of 10 fail** |
| Safari / WebKit | 26.6.2 | 10 of 10 kern |
| CoreText (native macOS) | 26.6.2 | 10 of 10 kern |
| HarfBuzz, whole string in one buffer | 14.4.0 | 10 of 10 kern |

Firefox is not included because it was not tested. Gecko does its own
itemisation and may or may not be affected.

### On trusting the negatives

The page reads two independent channels — DOM inline-box width and canvas
`measureText` — and counts a pair as kerned if *either* sees it. This matters:
WebKit's inline-box width ignores GPOS, so on the DOM channel alone Safari
reports every pair as unkerned, controls included. Reporting that as "WebKit
fails too" would have been wrong.

The first three rows are controls. They are inside a single script run by
construction, so if they were to fail, the measurement would be broken rather
than the engine. In Blink they pass on both channels while the Han↔Kana rows
fail on both.

## Where this comes from

`RunSegmenter` splits the text into script runs before shaping, and
`HarfBuzzShaper::Shape` shapes each segment independently:

```cpp
for (const RunSegmenter::RunSegmenterRange& segmented_range : ranges) {
  ShapeSegment(&range_data, segmented_range, result);
}
```

Font fallback happens *inside* `ShapeSegment`, so the split is decided from the
text alone, before any font is consulted — `RunSegmenter`'s constructor takes
only a text buffer and a `FontOrientation`. That is also why no font can work
around it. Thirty candidate separators were tried between a kanji and a kana,
including U+200B ZWSP, U+200D ZWJ, U+2060 WORD JOINER, U+034F CGJ, U+FE00 and
U+FE0E variation selectors and PUA; all thirty split. The same separators
between two kana do *not* split, which shows they reach GSUB and participate in
matching — the Han↔Kana split is a real run boundary, not the character being
dropped.

## Why this looks like an oversight rather than a decision

Blink already merges one such pair on purpose, for exactly this reason.
`script_run_iterator.cc`:

```cpp
// UScriptCode and OpenType script are not 1:1; specifically, both Hiragana and
// Katakana map to 'kana' in OpenType. They will be mapped correctly in
// HarfBuzz, but normalizing earlier helps to reduce splitting runs between
// these scripts.
// https://docs.microsoft.com/en-us/typography/opentype/spec/scripttags
inline UScriptCode GetScriptForOpenType(UChar32 ch, UErrorCode* status) {
  UScriptCode script = uscript_getScript(ch, status);
  ...
  if (script == USCRIPT_KATAKANA || script == USCRIPT_KATAKANA_OR_HIRAGANA)
    return USCRIPT_HIRAGANA;
  return script;
}
```

That is the あア row above, and the stated rationale — Unicode script
boundaries are not the boundaries OpenType cares about — applies to Han in
Japanese text just as directly.

Separately, `han_kerning.h` says:

> "OpenType features can't handle kerning at font boundaries by design."

`HanKerning` exists to emulate spacing the font cannot supply across a *font*
boundary, which is genuinely unavoidable. The boundary in this report is not:
Blink creates it.

## Would merging the runs change anything else?

Two things were checked, because they are the obvious objections.

**The OpenType script tag is a formality here.** Han maps to `hani` and Kana to
`kana`, so merging has to pick one. Shaping the same Han+Kana string with the
tag forced to `hani`, `kana` or `DFLT` produces an identical glyph stream, and
every shipping Japanese font checked registers the *same* feature set under
both tags:

| font | `hani` vs `kana` features |
|---|---|
| Hiragino Kaku Gothic W3 | identical |
| Hiragino Mincho ProN | identical |
| Hiragino Sans GB | identical |
| Noto Sans JP | identical |
| Arial Unicode (pan-Unicode, not a JP font) | differ — `locl salt smpl trad` under `hani` only |

**Neither script has a complex shaper.** HarfBuzz uses the default shaper for
both Han and Kana, so merging does not change which shaper runs.

What is *not* claimed to be free is font fallback. Today each segment resolves
a font independently; a merged run would have to resolve one. That is the real
risk, and it is what the suggestion below is built around.

## Suggested direction

Not `ScriptRunIterator`. Merging there would change which font gets picked, and
that is the part that cannot be argued to be safe.

Instead: merge adjacent Han and Kana segments **after fallback has resolved,
and only when both resolved to the same font.** Under that condition the merge
is a no-op by construction — the same font shapes the same characters with the
same features — and the only observable difference is that a lookup spanning
the boundary now fires. A font with no such lookup renders identically, bit for
bit.

A cheap approximation of that ordering, without restructuring the fallback
loop: resolve only the *first* fallback font per segment (a family lookup and a
coverage check), group adjacent segments that share it, and let the existing
reshape queue handle fallback within a group.

Happy to implement this behind a `base::Feature` so it can ride Canary and be
Finch-controlled, and to write the layout test — the repro font is 15 KB and
deterministic. Please say which direction you would prefer first; I have not
uploaded a CL.

## Smaller, separable bug

`ヶ` U+30F6 and `ヵ` U+30F5 are Katakana by property but are used as
abbreviations of 箇 *inside* Han words: 一ヶ月, 関ヶ原, 霞ヶ関. They therefore
split such a word into three runs. Scoped to two characters, this is a much
smaller change than the above and independent of it. Filed separately if
preferred.

## Disclosure of interest

The reporter maintains a font that renders furigana from GSUB, which is how
this was found: a rule keyed on a kanji plus its okurigana (生 + きる → い)
cannot match in Blink, so `生きる` gets no reading while an all-kanji word such
as 東京都新宿区 does. That use case is unusual and is not the argument here —
the kerning above is a plain GPOS pair in a font with no GSUB at all, and it is
what the report is asking about. Mentioned so the motivation is on the record.
