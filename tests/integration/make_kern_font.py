#!/usr/bin/env python3
"""A font that kerns across each script transition, to find which ones Blink honours.

The question this answers is not about YomiFont. It is whether an *ordinary*
Japanese font can position a kana relative to the kanji before it -- which is
something Japanese typography does routinely, and which `HanKerning` in Blink
exists to emulate because the font cannot be relied on to do it.

Each pair below gets a -500 unit kern, so a pair that reaches GPOS whole is
half an em narrower than one that does not. The Han-Han and Hira-Hira pairs are
controls: they are inside a single script run by construction, so if *they*
fail the probe is broken rather than the engine.

    PYTHONPATH=src ./tests/integration/make_kern_font.py dist/KernProbe.ttf
"""
from __future__ import annotations

import sys

from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.ttLib import TTFont

sys.path.insert(0, "src")

from yomifont.build import make_base_font  # noqa: E402

BASE = "data/raw/NotoSansJP-Regular.ttf"

# (label, first, second) -- what transition the pair crosses
PAIRS = [
    ("han-han",   "漢", "字"),   # control: one run
    ("hira-hira", "あ", "い"),   # control: one run
    ("kata-kata", "ア", "イ"),   # control: one run
    ("hira-kata", "あ", "ア"),   # Blink merges these two scripts on purpose
    ("han-hira",  "漢", "あ"),   # the one that matters
    ("hira-han",  "あ", "漢"),
    ("han-kata",  "漢", "ア"),
    ("kata-han",  "ア", "漢"),
    ("han-latin", "漢", "A"),
    ("han-digit", "漢", "1"),    # digits are Common and join the Han run
]

KERN = -500


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "dist/KernProbe.ttf"
    chars = {c for _, a, b in PAIRS for c in (a, b)}
    font = make_base_font(BASE, chars)
    cmap = font.getBestCmap()

    lines = []
    for _, a, b in PAIRS:
        lines.append(f"    pos {cmap[ord(a)]} {cmap[ord(b)]} {KERN};")
    fea = "feature kern {\n" + "\n".join(lines) + "\n} kern;\n"

    # A font with GPOS but no GDEF makes some engines skip positioning, so let
    # feaLib synthesise one.
    addOpenTypeFeaturesFromString(font, fea)
    font.save(out)

    reopened = TTFont(out, lazy=True)
    print(f"[kern] {out}: {reopened['maxp'].numGlyphs} glyphs, "
          f"tables {sorted(reopened.reader.tables)}")
    for label, a, b in PAIRS:
        print(f"       {label:<10} {a}{b}  {cmap[ord(a)]} {cmap[ord(b)]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
