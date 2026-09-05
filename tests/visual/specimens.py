#!/usr/bin/env python3
"""Visual regression: render specimens and build side-by-side contact sheets.

    ./tests/visual/specimens.py --a dist/phase1/YomiFont-Regular.ttf \
                                --b dist/YomiFont-Regular.ttf \
                                --out docs/images/typography.png

Each specimen is rendered with hb-view (HarfBuzz + FreeType, the same stack
Chrome and Android use) and the two fonts are stacked in one sheet so layout
changes are obvious. Also emits numeric typography metrics so regressions can
be caught without looking at the picture -- see `measure`.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

SPECIMENS = [
    # regressions from the stabilization pass
    "月", "一ヶ月", "月曜日", "今月", "新宿区", "東京都新宿区", "東京都渋谷区",
    "東京大学",
    # single groups
    "東京", "京都", "今日", "日本語", "学校", "図書館",
    # long single-group readings
    "日本語能力試験", "国際交流基金", "東京都新宿区",
    # ADJACENT groups -- this is where Phase 1 ran them together
    "東京大学", "日本語学校", "京都大学病院", "国際交流基金東京",
    # okurigana and multi-group words
    "行く", "行う", "食べる", "取り戻す", "承る",
    "富士山", "新幹線", "駅前", "自転車",
]
PARAGRAPHS = [
    "私は昨日東京へ行きました。",
    "日本語能力試験の勉強をしています。",
    "国際交流基金は東京都新宿区にあります。",
]

FONT_SIZE = 64
MARGIN = 18

# PIL's built-in bitmap font has no CJK, so every Japanese label in the row
# gutter came out as tofu. Any system font with kana will do.
LABEL_FONTS = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def label_font(size: int = 13):
    for path in LABEL_FONTS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def render(font_path: str, text: str, size: int = FONT_SIZE) -> Image.Image:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
        out = fh.name
    subprocess.run(
        ["hb-view", f"--font-file={font_path}", f"--font-size={size}",
         f"--margin={MARGIN}", f"--output-file={out}", "--output-format=png", text],
        check=True, capture_output=True,
    )
    img = Image.open(out).convert("RGB")
    os.unlink(out)
    return img


def measure(font_path: str, text: str) -> dict:
    """Typography metrics computed from glyph geometry, not from pixels."""
    sys.path.insert(0, os.path.join(ROOT, "tests", "shaping"))
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.ttLib import TTFont
    from shaper import shape_harfbuzz

    font = TTFont(font_path)
    gs = font.getGlyphSet()
    upem = font["head"].unitsPerEm
    pen_x = 0
    groups: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    ruby_bottom = None
    base_top = None
    for g in shape_harfbuzz(font_path, text):
        bp = BoundsPen(gs)
        gs[g.name].draw(bp)
        b = bp.bounds
        if g.ruby_char is not None:
            if b:
                cur.append((pen_x + b[0], pen_x + b[2]))
                ruby_bottom = b[1] if ruby_bottom is None else min(ruby_bottom, b[1])
        else:
            if cur:
                groups.append(cur)
                cur = []
            if b:
                base_top = b[3] if base_top is None else max(base_top, b[3])
        pen_x += g.advance
    if cur:
        groups.append(cur)

    spans = [(min(x0 for x0, _ in g), max(x1 for _, x1 in g)) for g in groups]
    gaps = [round((spans[i + 1][0] - spans[i][1]) / upem, 4)
            for i in range(len(spans) - 1)]
    # spacing evenness inside each group
    evenness = []
    for g in groups:
        if len(g) < 3:
            continue
        steps = [g[i + 1][0] - g[i][0] for i in range(len(g) - 1)]
        mean = sum(steps) / len(steps)
        if mean:
            evenness.append(round(max(abs(s - mean) for s in steps) / mean, 4))
    return {
        "ruby_groups": len(groups),
        "min_group_gap_em": min(gaps) if gaps else None,
        "group_gaps_em": gaps,
        "ruby_to_base_gap_em": (round((ruby_bottom - base_top) / upem, 4)
                                if ruby_bottom is not None and base_top is not None
                                else None),
        "max_overhang_left_em": round(-spans[0][0] / upem, 4) if spans else None,
        "worst_spacing_deviation": max(evenness) if evenness else 0.0,
    }


def sheet(a_path: str, b_path: str, out_path: str, a_label: str, b_label: str):
    rows = []
    small = label_font()
    for text in SPECIMENS:
        rows.append((text, render(a_path, text), render(b_path, text)))
    for text in PARAGRAPHS:
        rows.append((text, render(a_path, text, 44), render(b_path, text, 44)))

    label_w = 150
    col_w = max(max(a.width, b.width) for _, a, b in rows) + 24
    width = label_w + col_w * 2
    height = sum(max(a.height, b.height) for _, a, b in rows) + 46
    sheet_img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(sheet_img)
    d.text((label_w + 8, 8), a_label, fill="black", font=small)
    d.text((label_w + col_w + 8, 8), b_label, fill="black", font=small)
    d.line([(label_w + col_w, 0), (label_w + col_w, height)], fill="#ddd")

    y = 34
    for text, a, b in rows:
        d.text((8, y + 10), text[:14], fill="#666", font=small)
        sheet_img.paste(a, (label_w, y))
        sheet_img.paste(b, (label_w + col_w, y))
        h = max(a.height, b.height)
        d.line([(0, y + h), (width, y + h)], fill="#f0f0f0")
        y += h
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    sheet_img.save(out_path)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="dist/phase1/YomiFont-Regular.ttf")
    ap.add_argument("--b", default="dist/YomiFont-Regular.ttf")
    ap.add_argument("--a-label", default="Phase 1")
    ap.add_argument("--b-label", default="Phase 2")
    ap.add_argument("--out", default="docs/images/typography.png")
    ap.add_argument("--metrics", default="tests/visual/metrics.json")
    args = ap.parse_args()

    p = sheet(args.a, args.b, args.out, args.a_label, args.b_label)
    print(f"[visual] wrote {p}")

    report = {}
    for label, path in ((args.a_label, args.a), (args.b_label, args.b)):
        if not os.path.exists(path):
            continue
        report[label] = {t: measure(path, t) for t in SPECIMENS + PARAGRAPHS}
    os.makedirs(os.path.dirname(args.metrics) or ".", exist_ok=True)
    json.dump(report, open(args.metrics, "w"), ensure_ascii=False, indent=1)
    print(f"[visual] wrote {args.metrics}")

    for t in ("東京都新宿区", "日本語能力試験", "国際交流基金", "図書館", "東京"):
        line = f"  {t:12s}"
        for label in report:
            m = report[label].get(t, {})
            line += (f"  {label}: groups={m.get('ruby_groups')} "
                     f"min_gap={m.get('min_group_gap_em')} "
                     f"even={m.get('worst_spacing_deviation')} "
                     f"gap={m.get('ruby_to_base_gap_em')}")
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
