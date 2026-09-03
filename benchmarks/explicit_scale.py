#!/usr/bin/env python3
"""Explicit Ruby scales by *length*, not by vocabulary.

    ./benchmarks/explicit_scale.py [--out benchmarks/explicit_results.json]

The automatic side is benchmarked against the number of words it knows
(`scale.py`).  Explicit ruby knows no words at all, so that axis does not
exist: what it costs is set by

    base span length  x  ruby span length  x  ruby alphabet  x  placement grid

Each configuration is built with the *same* tiny lexical rule set, so every
difference measured here belongs to the explicit-ruby machinery.

The number that decides the default is `glyphs_total`: a TrueType font cannot
address more than 65,535 glyphs, and each ruby character has to exist once per
distinct (size, offset) the layout can ask for.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)

from scale import validate  # noqa: E402
from yomifont import build as build_mod, explicit  # noqa: E402
from yomifont.rules import Rule  # noqa: E402

CEILING = 65535

# A fixed, deliberately tiny lexical set: enough that the automatic path is
# present and interacting, small enough that it is not what is being measured.
LEX = [Rule(seq=s, groups=g, safety="SAFE_UNIQUE", origin="lex") for s, g in [
    ("東京", ((0, 2, "とうきょう"),)),
    ("日本語", ((0, 3, "にほんご"),)),
    ("図書館", ((0, 3, "としょかん"),)),
]]

# Explicit-ruby text of increasing span, plus ordinary text, so the cost of
# carrying the feature shows up even where it never fires.
BENCH_TEXT = [
    "｜月（ライト）",
    "|月(ライト)",
    "｜東京（とうきょう）",
    "｜日本語能力試験（にほんごのうりょくしけん）",
    "｜超絶暗黒剣（ダークネスブレード）",
    "昨日、｜月（ライト）を見た。",
    "私は昨日東京へ行きました。",          # no explicit markup at all
    "ひらがなだけのぶんしょうです。",       # nothing fires
]

CONFIGS = [
    # (base, ruby, grid)
    (4, 8, 100), (6, 12, 100), (8, 16, 100), (10, 20, 100), (12, 24, 100),
    (8, 16, 50), (8, 16, 150), (8, 16, 200),
    (16, 32, 200), (32, 64, 200),
]


def shape_bench(font_path: str, repeats: int = 60) -> dict:
    import uharfbuzz as hb

    face = hb.Face(hb.Blob.from_file_path(font_path))
    font = hb.Font(face)
    warm = hb.Buffer()
    warm.add_str(BENCH_TEXT[0])
    warm.guess_segment_properties()
    t0 = time.perf_counter()
    hb.shape(font, warm)
    first_ms = (time.perf_counter() - t0) * 1000

    per_text = {}
    for s in BENCH_TEXT:
        times = []
        for _ in range(repeats):
            buf = hb.Buffer()
            buf.add_str(s)
            buf.guess_segment_properties()
            t0 = time.perf_counter()
            hb.shape(font, buf)
            times.append((time.perf_counter() - t0) * 1e6)
        per_text[s] = round(statistics.median(times) / len(s), 2)
    explicit_texts = [s for s in BENCH_TEXT if "｜" in s or "|" in s]
    plain = [s for s in BENCH_TEXT if s not in explicit_texts]
    return {
        "first_shape_ms": round(first_ms, 3),
        "us_per_char_explicit": round(
            statistics.median([per_text[s] for s in explicit_texts]), 2),
        "us_per_char_plain": round(
            statistics.median([per_text[s] for s in plain]), 2),
        "per_text_us_per_char": per_text,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="benchmarks/explicit_results.json")
    ap.add_argument("--keep-fonts", action="store_true")
    ap.add_argument("--latin", action="store_true",
                    help="also measure Latin and digits inside the ruby")
    args = ap.parse_args()

    os.makedirs("build", exist_ok=True)
    results = []
    for base, ruby, grid in CONFIGS:
        limits = explicit.Limits(base, ruby)
        alpha = explicit.alphabet(args.latin)
        cost = explicit.cost(alpha, limits, grid=grid)
        label = f"b{base}_r{ruby}_g{grid}"
        path = f"build/bench_explicit_{label}.ttf"
        gc.collect()
        # The base repertoire self-budgets against the ceiling, so the only
        # configuration that cannot be built is one whose ruby inventory alone
        # does not fit. Report it rather than crashing mid-build.
        projected = cost["ruby_glyphs"] + 6_000
        if projected > CEILING:
            print(f"[bench] {label:>16s} SKIPPED: {cost['ruby_glyphs']} ruby glyphs "
                  f"+ base repertoire would exceed the {CEILING}-glyph ceiling")
            results.append({**cost, "label": label, "over_ceiling": True,
                            "projected_glyphs": projected})
            continue
        info = build_mod.build_font(LEX, out_path=path, family=f"YomiEx{label}",
                                    verbose=False, explicit=limits,
                                    explicit_grid=grid, explicit_latin=args.latin)
        info.update({"label": label, "over_ceiling": False})
        info.update(validate(path))
        info["shaping"] = shape_bench(path)
        info["glyph_headroom"] = CEILING - info["glyphs"]
        results.append(info)
        ex = info["explicit"]
        print(f"[bench] {label:>16s} expr={ex['expressions']:>4d} "
              f"pairs={ex['offset_pairs']:>4d} "
              f"glyphs={info['glyphs']:>6d} (headroom {info['glyph_headroom']:>6d}) "
              f"gsub={info['gsub_bytes']/1e6:5.2f}MB "
              f"font={info['font_bytes']/1e6:5.2f}MB "
              f"build={info['build_seconds']:5.1f}s "
              f"shape={info['shaping']['us_per_char_explicit']:5.2f}/"
              f"{info['shaping']['us_per_char_plain']:.2f}us "
              f"ots={info['ots']}")
        if not args.keep_fonts:
            os.remove(path)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    json.dump(results, open(args.out, "w"), indent=1)
    print(f"[bench] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
