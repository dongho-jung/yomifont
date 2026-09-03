# OpenType notes

Findings from building YomiFont, in the order they cost debugging time.
Everything here was verified with a test font, not read off a specification.

---

## 1. lsb must equal xMin or baked-in offsets vanish

**The bug.** The first working proof-of-concept produced a stack of ruby kana
piled on top of each other at x≈0 instead of spread across the word — even
though dumping the compiled `glyf` table showed the composite offsets were
correct (`r.3046.t7` had bbox x∈[1833, 2152]).

**The cause.** A TrueType rasterizer re-origins every glyph outline by
`(lsb − xMin)`. FreeType's `TT_Process_Simple_Glyph` does:

```c
loader->pp1.x = loader->bbox.xMin - loader->left_bearing;
if (loader->pp1.x)
    FT_Outline_Translate(outline, -loader->pp1.x, 0);
```

The ruby glyphs had `hmtx = (advance 0, lsb 0)` while their `xMin` was
anywhere from −250 to +2000, so the rasterizer translated the entire baked-in
offset away. `lsb == xMin` is the normal condition for every glyph in every
font, which is exactly why it is easy to violate when synthesising glyphs — and
why doing so is safe once fixed: with `lsb == xMin` the translation is a no-op
in every engine.

**The fix** (`rubyglyphs.py`):

```python
glyf.glyphs[name].recalcBounds(glyf)
hmtx.metrics[name] = (0, glyf.glyphs[name].xMin)
```

There is no vertical equivalent applied in horizontal layout, which is why the
ruby was at the right *height* the whole time — a misleading symptom.

---

## 2. Two glyph-inserting lookup records in one context rule are not portable

**The bug.** `取り戻す` should get two ruby groups (と over 取, もど over 戻).
The natural encoding is one context rule with two `SequenceLookupRecord`s, at
sequence indices 0 and 2. HarfBuzz silently emitted only the first group.

**The cause.** When a nested lookup changes the glyph count, HarfBuzz rewrites
`match_positions` so subsequent indices address the *current* buffer:

```c
memmove (match_positions + next + delta, match_positions + next, ...);
next += delta;  match_length += delta;
for (unsigned j = idx + 1; j < next; j++)
    match_positions[j] = match_positions[j - 1] + 1;
```

After the first record inserted one glyph, `sequenceIndex = 2` pointed at `り`,
not `戻`. Whether an implementation is *supposed* to renumber is exactly the
kind of thing engines disagree about, so relying on either behaviour is a bug.

**The fix.** Emit *all* of a word's ruby from a single record at sequence index
0, folding each group's position into the ruby glyph's `t` value:

```
t = 4·group_start + 2·span − n_kana + 2·i
```

Every rule now has exactly one lookup record, and the ambiguity cannot arise.
This also removed the need to reason about record ordering at all.

---

## 3. Blink shapes Han and Kana as separate runs

**The bug.** Chrome rendered `行った` with ぎょう where HarfBuzz and CoreText
both produced い.

**The cause.** Blink itemises a text node into script runs *before* handing
anything to HarfBuzz. `行` (Han) and `った` (Kana) are different scripts, so
they become two shaping calls. A GSUB rule can never see across that boundary.

Verified by prediction: for every test string, Chrome's output is exactly what
HarfBuzz produces for each maximal Han run shaped in isolation.

| text | HarfBuzz / CoreText | Chrome | HarfBuzz on the lone Han run |
|---|---|---|---|
| 行った | い | ぎょう | 行 → ぎょう |
| 分かりました | わ | ふん | 分 → ふん |
| 食べる | た | しょく | 食 → しょく |
| 取り戻す | と / もど | とり | 取 → とり, 戻 → (none) |
| 日本語 | にほんご | にほんご | (all-Han, unaffected) |

CoreText does *not* do this; Safari and native macOS controls match HarfBuzz.

**The mitigation.** The single-character rule for a kanji is set to the reading
that kanji actually takes when it stands alone between kana, counted over the
training corpus with the same okurigana alignment the compiler uses
(`行 → い` 3868 times vs `行 → ぎょう` 25). The reading is never invented — it
must already be one YomiFont assigns to that character elsewhere. This recovers
Blink from 71.4 % to 91.3 % correct tokens at a cost of 0.5 points in
non-segmenting engines. Numbers in [compatibility.md](compatibility.md).

**What this does not fix.** In Blink, `行う` and `行く` are indistinguishable;
both get い. Okurigana-based disambiguation genuinely does not exist there.

---

## 4. Nested composites dodge the SCALED_COMPONENT_OFFSET ambiguity

A ruby glyph needs both a 0.5 scale and a translation. A single composite that
does both is ambiguous: the Apple convention applies the offset in the
component's scaled space, the Microsoft convention in the parent's, selected by
`SCALED_COMPONENT_OFFSET` (0x0800) / `UNSCALED_COMPONENT_OFFSET` (0x1000) —
flags not every rasterizer honours identically.

YomiFont splits the transform across two levels so neither level is ambiguous:

```
rk.304D       composite(uni304D, scale 0.5, offset 0/0)   # scale, no offset
r.304D.t3     composite(rk.304D, scale 1.0, offset 750/900)  # offset, no scale
```

With a zero offset at the scaling level and an identity scale at the offsetting
level, both conventions produce the same result. Cost is ~14 bytes per variant.

---

## 5. Table limits actually encountered

| limit | value | hit? |
|---|---|---|
| glyph count | 65,535 | no — 9,275 used |
| Lookup subtable offsets | `Offset16` from Lookup start | avoided: subtables capped at 48 kB and packed by first glyph |
| LookupList offsets | `Offset16` from LookupList start | no — 1,446 lookups, all small |
| ChainContextSubst fmt 1 internal offsets | `Offset16` from subtable start | avoided by the 48 kB budget → 141 subtables |
| HarfBuzz repacker | fails somewhere between a **8.7 MB and 9.2 MB** GSUB | **yes** |

The repacker limit is the only hard wall found. fontTools tries HarfBuzz's
`hb.repack` first and falls back to its own pure-Python overflow resolution:

| rules | GSUB | repacker | save time |
|---|---|---|---|
| 200,000 | 5.9 MB | ok | 10.0 s |
| 300,000 | 8.7 MB | ok | 18.9 s |
| 318,538 | 9.2 MB | **fails → fallback** | 83.8 s |

The fallback still produces a font that passes OpenType Sanitizer and shapes
identically; it is 4.5× slower to write. This bounds the practical single-font
rule set at roughly 300k rules before build time degrades sharply.

---

## 6. Choices that turned out to matter

**`ccmp`, not `calt` or `liga`.** `ccmp` is in HarfBuzz's *common* feature set,
applied for every script, and — unlike `liga`/`calt` — is not something
applications offer users a switch to disable. It is also the feature
semantically intended for glyph-count-changing composition.

**ChainContextSubst Format 1, not Format 3.** Format 3 encodes exactly one rule
per subtable; 318k rules would mean 318k subtables, past the ~6,500 that fit in
one Extension lookup and catastrophic for the per-position subtable scan.
Format 1 keys rule sets by first glyph, so one subtable holds thousands of
rules. All rules sharing a first glyph must land in the *same* subtable, or a
shorter rule in an earlier subtable beats a longer one in a later one and
longest-match silently breaks.

**Longest match is rule order.** Within a `ChainSubRuleSet`, engines try rules
in array order and stop at the first match, so the compiler emits them
longest-first. This has a consequence for the linguistics: **rule length beats
priority**. `今日は` (こんにちは) is a real JMdict entry and, being longer, will
always beat `今日` — no amount of demotion helps. Such entries have to be
dropped from the rule set, not down-ranked.

**Whole word as input, no lookahead.** Marking every character of the word as
*input* makes the lookup consume the whole match, so scanning resumes after 語
in 日本語 rather than re-entering at 本.

**No GPOS.** Baking placement into outlines removes an entire table an engine
could handle differently, and removes the question of whether a positioning
feature is enabled. The cost is ~3,262 composite glyphs, about 70 kB.

---

## 7. Vertical writing

Ruby offsets are baked in as *horizontal* displacements, which are meaningless
in tategaki. Rather than scatter ruby across the column, YomiFont maps every
ruby glyph to a blank under `vert`/`vrt2`, and carries the base font's
punctuation rotations across. Vertical text therefore renders correctly but
without furigana. Proper vertical ruby needs a second positional inventory and
is future work.

## References consulted

- [OpenType GSUB specification](https://learn.microsoft.com/en-us/typography/opentype/spec/gsub)
- [OpenType GPOS specification](https://learn.microsoft.com/en-us/typography/opentype/spec/gpos)
- [OpenType `hmtx`](https://learn.microsoft.com/en-us/typography/opentype/spec/hmtx) and [`glyf`](https://learn.microsoft.com/en-us/typography/opentype/spec/glyf) (composite glyph flags)
- [HarfBuzz source](https://github.com/harfbuzz/harfbuzz) — `hb-ot-layout-gsubgpos.hh` for `apply_lookup` / `match_positions`
- [FreeType](https://gitlab.freedesktop.org/freetype/freetype) — `ttgload.c` for the lsb/xMin translation
- [OpenType Sanitizer](https://github.com/khaledhosny/ots)
- [fontTools](https://github.com/fonttools/fonttools) — `otBase.py` overflow resolution
