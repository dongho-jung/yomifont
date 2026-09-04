#!/usr/bin/env python3
"""Where do the glyphs go, and what would it take to get some back?

    PYTHONPATH=src ./scripts/glyph_budget.py [font]

A TrueType font addresses glyphs with a uint16, so 65,535 is a hard wall and
the build now runs close to it.  This classifies every glyph in a built font by
what it is for, and then prices the levers that could recover headroom.
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

from yomifont import explicit as ex  # noqa: E402
from yomifont.layout import EM, QUANTUM  # noqa: E402

CEILING = 65535


def classify(font_path: str) -> dict:
    font = TTFont(font_path, lazy=True)
    order = font.getGlyphOrder()
    cmap = font.getBestCmap()
    encoded = set(cmap.values())

    kinds: Counter = Counter()
    ruby_pos: Counter = Counter()   # explicit (negative slot) vs automatic
    ruby_size: Counter = Counter()
    ruby_kana: set = set()
    for n in order:
        if n.startswith("r."):
            kinds["ruby variant"] += 1
            parts = n.split(".")
            cp, size, slot = parts[1], parts[2], parts[3]
            ruby_kana.add(cp)
            ruby_size[size] += 1
            ruby_pos["explicit (left of the pen)" if slot.startswith("m")
                     else "automatic (right of the pen)"] += 1
        elif n.startswith("rk."):
            kinds["ruby scaled source"] += 1
        elif n.startswith("rsrc."):
            kinds["ruby outline import"] += 1
        elif n.startswith("x."):
            kinds["protected base duplicate"] += 1
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
        "ruby_by_side": dict(ruby_pos),
        "ruby_by_size": {f"{int(k)/100}": v for k, v in sorted(ruby_size.items())},
        "distinct_ruby_kana": len(ruby_kana),
    }


def levers(alphabet_size: int) -> list[dict]:
    """Price each way of buying headroom back, at the shipping limits."""
    out = []
    base_line = ex.cost(ex.alphabet(), ex.DEFAULT_LIMITS, grid=ex.GRID)
    for grid in (100, 150, 200, 250):
        c = ex.cost(ex.alphabet(), ex.DEFAULT_LIMITS, grid=grid)
        out.append({"lever": f"placement grid {grid} units ({grid/EM:.2f} em)",
                    "explicit_glyphs": c["ruby_glyphs"],
                    "saved": base_line["ruby_glyphs"] - c["ruby_glyphs"],
                    "note": "coarser lattice; costs spacing evenness"})
    for b, n in ((8, 16), (6, 12), (8, 12), (6, 16)):
        c = ex.cost(ex.alphabet(), ex.Limits(b, n), grid=ex.GRID)
        out.append({"lever": f"limits base<={b} ruby<={n}",
                    "explicit_glyphs": c["ruby_glyphs"],
                    "saved": base_line["ruby_glyphs"] - c["ruby_glyphs"],
                    "note": "costs expression length"})
    pairs = base_line["offset_pairs"]
    for drop, what in ((6, "drop ゝゞヽヾ〜・"), (12, "drop rare hiragana ゐゑゔゕゖ + rare katakana"),
                       (62, "the Latin/digit ruby option, if it were on")):
        out.append({"lever": f"ruby alphabet {what}",
                    "explicit_glyphs": (alphabet_size - drop) * pairs,
                    "saved": drop * pairs,
                    "note": f"each ruby character costs {pairs} glyphs"})
    return out


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
    print(f"\n  ruby variants by side: {res['ruby_by_side']}")
    print(f"  ruby variants by size: {res['ruby_by_size']}")
    print(f"  distinct ruby kana:    {res['distinct_ruby_kana']}")

    print(f"\nlevers, against the shipping configuration "
          f"(base<={ex.DEFAULT_LIMITS.base} ruby<={ex.DEFAULT_LIMITS.ruby} "
          f"grid={ex.GRID}):")
    lv = levers(len(ex.alphabet()))
    for row in lv:
        sign = "+" if row["saved"] < 0 else " "
        print(f"  {row['lever']:<44} {row['explicit_glyphs']:>7} glyphs  "
              f"{sign}{abs(row['saved']):>6} saved   {row['note']}")
    res["levers"] = lv
    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    json.dump(res, open(args.report, "w"), ensure_ascii=False, indent=1)
    print(f"\nwrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
