# Experiments

`poc1_tokyo.py` is the original architectural checkpoint, kept as-is for the
record. It builds a 95-glyph font from a 13-word vocabulary and was used to
establish, before any of the real compiler existed, that:

1. GSUB MultipleSubst nested inside a ChainContextSubst inserts ruby glyphs
   into the stream while leaving the text buffer untouched;
2. reusable positional ruby glyphs render correctly with **no GPOS**;
3. longest match works (日本語 beats 日本);
4. okurigana context selects between readings of the same kanji (行く / 行う).

It is also where the two portability traps in
[../docs/opentype-notes.md](../docs/opentype-notes.md) were found: the lsb/xMin
re-origining rule, and multi-record sequence-index drift.

```
.venv/bin/python experiments/poc1_tokyo.py
hb-shape --font-file=build/poc1.ttf 東京
hb-view  --font-file=build/poc1.ttf --font-size=72 --output-file=/tmp/a.png \
         --output-format=png "東京 京都 今日 日本語"
```
