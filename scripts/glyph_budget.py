#!/usr/bin/env python3
"""Where do the glyphs go, and what would it take to get some back?

    PYTHONPATH=src ./scripts/glyph_budget.py [font]

A TrueType font addresses glyphs with a uint16, so 65,535 is a hard wall.  The
build has plenty of room since explicit ruby was dropped, but the ruby
inventory grows with the rule set, so this classifies every glyph in a built
font by what it is for and reports the headroom left.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from fontTools.ttLib import TTFont  # noqa: E402

CEILING = 65535


def classify(font_path: str) -> dict:
    font = TTFont(font_path, lazy=True)
    order = font.getGlyphOrder()
    cmap = font.getBestCmap()
    encoded = set(cmap.values())

    kinds: Counter = Counter()
    ruby_size: Counter = Counter()
    ruby_kana: set = set()
    for n in order:
        if n.startswith("r."):
            kinds["ruby variant"] += 1
            parts = n.split(".")
            cp, size = parts[1], parts[2]
            ruby_kana.add(cp)
            ruby_size[size] += 1
        elif n.startswith("rk."):
            kinds["ruby scaled source"] += 1
        elif n.startswith("rsrc."):
            kinds["ruby outline import"] += 1
        elif n == "ruby.blank":
            kinds["blank"] += 1
        elif n in encoded:
            kinds["base repertoire (encoded)"] += 1
        else:
            kinds["base font leftovers (unencoded)"] += 1

    return {
        "font": font_path,
        "total": len(order),
        "headroom": CEILING - len(order),
        "by_kind": dict(kinds.most_common()),
        "ruby_by_size": {f"{int(k)/100}": v for k, v in sorted(ruby_size.items())},
        "distinct_ruby_kana": len(ruby_kana),
    }



def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("font", nargs="?", default="dist/YomiFont-Regular.ttf")
    ap.add_argument("--report", default="data/normalized/glyph_budget.json")
    args = ap.parse_args()

    res = classify(args.font)
    print(f"{res['font']}: {res['total']} glyphs, {res['headroom']} spare "
          f"of {CEILING}\n")
    w = max(len(k) for k in res["by_kind"])
    for k, v in res["by_kind"].items():
        print(f"  {k:<{w}}  {v:>7}  {100*v/res['total']:5.1f} %")
    print(f"\n  ruby variants by size: {res['ruby_by_size']}")
    print(f"  distinct ruby kana:    {res['distinct_ruby_kana']}")

    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    json.dump(res, open(args.report, "w"), ensure_ascii=False, indent=1)
    print(f"\nwrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
