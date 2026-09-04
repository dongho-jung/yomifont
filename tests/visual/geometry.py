#!/usr/bin/env python3
"""Geometric checks on rendered ruby: overlap, spacing, overhang, clipping.

    PYTHONPATH=src:tests/shaping ./tests/visual/geometry.py [font]

Ruby groups that touch are a correctness bug, not a preference: two readings
run together are one unreadable string.  These checks work on glyph geometry
rather than pixels, so they are exact and rasteriser-independent.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests", "shaping"))

from fontTools.pens.boundsPen import BoundsPen  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

from shaper import shape_harfbuzz  # noqa: E402

# Strings whose ruby groups sit next to each other, which is where collisions
# happen. Several of these were reported as visually merged.
ADJACENT = [
    "東京都新宿区", "東京都渋谷区", "東京都千代田区", "東京大学", "日本語学校",
    "京都大学病院", "国際交流基金東京", "日本語能力試験", "国際交流基金",
    "私は昨日東京へ行きました。", "取り戻す", "申し込み",
    "一ヶ月", "月曜日", "新宿区", "東京都",
]

# JLREQ puts a visible gap between adjacent ruby groups; anything at or below
# zero is a collision.
MIN_GAP_EM = 0.02


def boxes(font_path: str, text: str):
    """[(x0, x1, kana)] for every ruby glyph, in font units along the line.

    Per glyph, not per group: a group boundary is not observable in the glyph
    stream anyway, because all of a rule's ruby is emitted from one
    substitution at the word's first glyph, so と and もど in 取り戻す arrive
    as one contiguous run. Checking every adjacent pair of ruby outlines
    catches collisions *between* groups and *inside* one alike, and needs no
    grouping to be inferred.
    """
    font = TTFont(font_path)
    gs = font.getGlyphSet()
    pen_x = 0
    out = []
    for g in shape_harfbuzz(font_path, text):
        if g.ruby_char is not None:
            bp = BoundsPen(gs)
            gs[g.name].draw(bp)
            if bp.bounds:
                out.append((pen_x + bp.bounds[0], pen_x + bp.bounds[2], g.ruby_char))
        pen_x += g.advance
    return sorted(out)


def groups(font_path: str, text: str, split_em: float = 0.5):
    """[(x0, x1, reading)] per *visual* group, split where the kana pull apart."""
    upem = TTFont(font_path, lazy=True)["head"].unitsPerEm
    out, cur = [], []
    for b in boxes(font_path, text):
        if cur and b[0] - cur[-1][1] > split_em * upem:
            out.append((cur[0][0], max(x for _, x, _ in cur),
                        "".join(c for _, _, c in cur)))
            cur = []
        cur.append(b)
    if cur:
        out.append((cur[0][0], max(x for _, x, _ in cur),
                    "".join(c for _, _, c in cur)))
    return out


def check(font_path: str, texts=ADJACENT) -> dict:
    upem = TTFont(font_path, lazy=True)["head"].unitsPerEm
    rows, collisions, overlaps = [], [], []
    for text in texts:
        bs = boxes(font_path, text)
        # every adjacent pair of ruby outlines, group boundaries or not
        pairs = [round((bs[i + 1][0] - bs[i][1]) / upem, 4) for i in range(len(bs) - 1)]
        for i, gap in enumerate(pairs):
            if gap < 0:
                overlaps.append({"text": text, "left": bs[i][2],
                                 "right": bs[i + 1][2], "overlap_em": -gap})
        gs = groups(font_path, text)
        gaps = [round((gs[i + 1][0] - gs[i][1]) / upem, 4) for i in range(len(gs) - 1)]
        rows.append({"text": text, "groups": len(gs),
                     "readings": [r for _, _, r in gs], "gaps_em": gaps,
                     "min_gap_em": min(gaps) if gaps else None,
                     "min_kana_gap_em": min(pairs) if pairs else None})
        for i, gap in enumerate(gaps):
            if gap < MIN_GAP_EM:
                collisions.append({"text": text, "between": i,
                                   "left": gs[i][2], "right": gs[i + 1][2],
                                   "gap_em": gap})
    return {"min_gap_em_required": MIN_GAP_EM, "rows": rows,
            "collisions": collisions, "overlaps": overlaps}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("font", nargs="?", default="dist/YomiFont-Regular.ttf")
    ap.add_argument("--report", default="tests/visual/geometry.json")
    args = ap.parse_args()

    res = check(args.font)
    for r in res["rows"]:
        flag = ""
        if r["min_gap_em"] is not None and r["min_gap_em"] < MIN_GAP_EM:
            flag = "  <-- COLLISION"
        print(f"  {r['text']:<16} groups={r['groups']} "
              f"min_gap={r['min_gap_em']} kana_gap={r['min_kana_gap_em']} "
              f"{r['readings']}{flag}")
    print(f"\n{len(res['overlaps'])} outline overlaps, "
          f"{len(res['collisions'])} group collisions "
          f"(gap < {MIN_GAP_EM} em) in {len(res['rows'])} strings")
    for o in res["overlaps"]:
        print(f"   OVERLAP {o['text']}: {o['left']!r}/{o['right']!r} "
              f"by {o['overlap_em']} em")
    for c in res["collisions"]:
        print(f"   TIGHT   {c['text']}: {c['left']!r} | {c['right']!r} "
              f"gap={c['gap_em']} em")
    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    json.dump(res, open(args.report, "w"), ensure_ascii=False, indent=1)
    return 1 if (res["collisions"] or res["overlaps"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
