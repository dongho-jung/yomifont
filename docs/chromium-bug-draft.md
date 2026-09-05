# Chromium bug report — draft

Filed against **`Chromium > Blink > Fonts`** (component id 1456925, from
`third_party/blink/renderer/platform/fonts/DIR_METADATA`).

The form has a **Markdown** checkbox under the Description box. Tick it, or the
tables below arrive as one run-on paragraph.

Two parts on purpose. The **Description** is the bug: repro, expected, actual,
environment. The **first comment** is the analysis and the suggested fix. A
reporter who has already decided what the fix should be reads as someone who
has not really looked, and an owner who only wants to know whether the bug is
real should not have to scroll past a proposal to find out.

---

## Title

```
Font kerning is not applied across a Han↔Kana boundary
```

---

## Description — paste this

A font that declares a `kern` pair between a kanji and the kana that follows it
has no effect in Chrome. The same font kerns the same pair in Safari, in native
macOS text, and in HarfBuzz when the string is shaped in one buffer.

### Steps to reproduce

Save the attached `blink-han-kana-kerning-repro.html` and open it. It is
self-contained: no server, no external resources.

It embeds a 148-glyph subset of Noto Sans JP (SIL OFL 1.1) whose only feature
is a `kern` pair of −500/1000 em on each transition in the table. The font has
no GSUB. At 100 px that kern is 50 px, so a pair that reached GPOS as one run
measures 50 px narrower than its two characters measured separately. The page
prints the table below.

### Expected

All ten pairs are kerned. The font declares a `kern` pair for each and
`font-kerning: normal` is in effect.

### Actual — Chrome 152.0.7977.76

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
follows it — the most common adjacency in the language.

The first three rows are controls: they sit inside a single script run by
construction, so if they were to report "no" the measurement would be broken
rather than the engine. The page reads two independent channels, DOM
inline-box width and canvas `measureText`, and counts a pair as kerned if
either sees it. That matters for the cross-engine numbers below: WebKit's
inline-box width ignores GPOS, so on the DOM channel alone Safari reports every
pair unkerned, controls included.

### Other engines, same font

| engine | version | result |
|---|---|---|
| Chrome / Blink | 152.0.7977.76 | 5 of 10 fail |
| Safari / WebKit | 26.6.2 | 10 of 10 kern |
| CoreText, via a direct shaping call | macOS 26.6.2 | 10 of 10 kern |
| HarfBuzz, whole string in one buffer | 14.4.0 | 10 of 10 kern |

Firefox is not in the table because it was not tested.

### Environment

Chrome 152.0.7977.76, macOS 26.6.2. Not verified on Windows or Linux — the code
path does not appear to be platform-specific, but I have not checked, so please
read "OS: All" as an assumption rather than a measurement.

I have some notes on where this comes from and on whether changing it could be
made safe. Adding them as a comment rather than inline here.

---

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

**The OpenType script tag looks like a formality here.** Han maps to `hani` and
Kana to `kana`, so a merge has to pick one. Shaping the same Han+Kana string
with the tag forced to `hani`, `kana` or `DFLT` gave me an identical glyph
stream, and every shipping Japanese font I checked registers the same feature
set under both tags:

| font | `hani` vs `kana` |
|---|---|
| Hiragino Kaku Gothic W3 | identical |
| Hiragino Mincho ProN | identical |
| Hiragino Sans GB | identical |
| Noto Sans JP | identical |
| Arial Unicode (pan-Unicode, not a JP font) | differ — `locl salt smpl trad` under `hani` only |

**Neither script has a complex shaper**, so merging does not change which
shaper runs.

What I am *not* claiming is free is font fallback. Today each segment resolves
a font independently; a merged run has to resolve one. That is the real risk.

### A direction that avoids that risk

Not `ScriptRunIterator` — merging there changes which font gets picked, which
is the part that cannot be argued to be safe.

Instead: merge adjacent Han and Kana segments **after fallback has resolved,
and only when both resolved to the same font**. Under that condition the merge
is a no-op by construction — the same font shapes the same characters with the
same features — and the only observable difference is that a lookup spanning
the boundary now fires. A font with no such lookup renders identically.

A cheaper approximation of the same ordering, without restructuring the
fallback loop: resolve only the first fallback font per segment, group adjacent
segments that share it, and let the existing reshape queue handle fallback
inside a group.

I am happy to implement this behind a `base::Feature` and write the layout
test — the probe font is 15 KB and deterministic — but I would rather hear
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
  non-CJK scripts" (P2) — overlaps the 漢A row above
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
