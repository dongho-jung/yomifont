#!/usr/bin/env python3
"""Compare browser probe reports against a HarfBuzz reference.

    # 1. serve the repo
    ./tests/integration/server.py &
    # 2. open http://127.0.0.1:8777/tests/integration/engine_probe.html in each
    #    browser you want to test (it POSTs its results back)
    # 3. compare
    ./tests/integration/compare_engines.py

The reference is computed from glyph geometry -- shape with HarfBuzz, look up
each ruby glyph's bounding box in `glyf`, and mark the em-columns it covers.
That is exact and independent of any rasteriser, so a browser that draws the
same glyphs in the same places matches it regardless of antialiasing.
"""
from __future__ import annotations

import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests", "shaping"))

from fontTools.pens.boundsPen import BoundsPen  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402
from shaper import ruby_runs, shape_harfbuzz  # noqa: E402

FONT = os.environ.get("YOMIFONT", os.path.join(ROOT, "dist", "YomiFont-Regular.ttf"))
B0, B1, BUCKET = -20, 140, 50  # 1/20 em buckets from -1 em to +7 em
# Below this, the browser is drawing different glyphs, not just different pixels.
SAME_GLYPHS = 0.88


def reference_bits(font: TTFont, gs, text: str, cache: dict) -> str:
    on: set[int] = set()
    pen = 0
    for g in shape_harfbuzz(FONT, text):
        if g.name not in cache:
            bp = BoundsPen(gs)
            gs[g.name].draw(bp)
            cache[g.name] = bp.bounds
        b = cache[g.name]
        if b and g.ruby_char is not None:
            lo, hi = pen + b[0], pen + b[2]
            for k in range(B0, B1):
                if hi > k * BUCKET and lo < (k + 1) * BUCKET:
                    on.add(k)
        pen += g.advance
    return "".join("#" if k in on else "." for k in range(B0, B1))


def similarity(ref: str, got: str) -> float:
    """Bucket agreement, tolerating one bucket of antialiasing spill."""
    if len(ref) != len(got):
        return 0.0
    ok = 0
    for i, (a, b) in enumerate(zip(ref, got)):
        if a == b:
            ok += 1
        elif a == "#" and "#" in got[max(0, i - 1): i + 2]:
            ok += 1
        elif b == "#" and "#" in ref[max(0, i - 1): i + 2]:
            ok += 1
    return ok / len(ref)


def main() -> int:
    font = TTFont(FONT)
    gs = font.getGlyphSet()
    cache: dict = {}

    reports = {}
    for path in sorted(glob.glob(os.path.join(HERE, "reports", "*.json"))):
        d = json.load(open(path))
        reports[d["engine"]] = d["results"]
    if not reports:
        print("no reports; open engine_probe.html in a browser first")
        return 1

    names = sorted(reports)
    print(f"font: {FONT}")
    print(f"{'text':<14}{'HarfBuzz ruby':<22}" + "".join(f"{n[:20]:<22}" for n in names))
    print("-" * (36 + 22 * len(names)))
    failures = []
    for text in next(iter(reports.values())):
        ref = reference_bits(font, gs, text, cache)
        hb = "/".join(ruby_runs(shape_harfbuzz(FONT, text))) or "(none)"
        cells = []
        for n in names:
            got = reports[n][text].get("bits", "")
            s = 1.0 if (not got and ref.count("#") == 0) else similarity(ref, got)
            cells.append(f"{100*s:5.1f}%" + ("" if s >= SAME_GLYPHS else "  DIFFERS"))
            if s < SAME_GLYPHS:
                failures.append((n, text, s))
        print(f"{text:<14}{hb:<22}" + "".join(f"{c:<22}" for c in cells))

    print()
    if failures:
        print("engines drawing different glyphs than HarfBuzz:")
        for n, t, s in failures:
            print(f"   {n}  {t}  ({100*s:.1f}%)")
        return 1
    print("every engine draws the same ruby glyphs as HarfBuzz.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
