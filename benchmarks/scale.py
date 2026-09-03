#!/usr/bin/env python3
"""Scaling benchmark: build YomiFont at increasing rule counts and measure.

    ./benchmarks/scale.py [--sizes 1000,10000,...] [--out benchmarks/results.json]

For each size we record font size, GSUB size, glyph count, build time, whether
the font validates, and shaping latency measured with uharfbuzz over a fixed
corpus.  This is the evidence for "how large can the lexical rule set become".
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import resource
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from yomifont import build as build_mod, rules as rules_mod  # noqa: E402

SENTENCES = [
    "私は昨日東京へ行きました。",
    "日本語を勉強しています。",
    "今日の天気はいいですね。",
    "大人になってから分かりました。",
    "市場を調査しています。",
    "人気のない山道を歩いた。",
    "この商品は人気があります。",
    "ご飯を食べました。",
    "この行いは正しい。",
    "銀行へ行った。",
    "彼女は先週から新しい仕事を始めたそうです。",
    "国際的な会議が来月開催される予定になっている。",
]


def shape_bench(font_path: str, repeats: int = 40) -> dict:
    import uharfbuzz as hb

    blob = hb.Blob.from_file_path(font_path)
    t0 = time.perf_counter()
    face = hb.Face(blob)
    font = hb.Font(face)
    load_ms = (time.perf_counter() - t0) * 1000

    # warm up (HarfBuzz builds lookup accelerators lazily on first shape)
    buf = hb.Buffer()
    buf.add_str(SENTENCES[0])
    buf.guess_segment_properties()
    t0 = time.perf_counter()
    hb.shape(font, buf)
    first_shape_ms = (time.perf_counter() - t0) * 1000

    per_sentence = []
    total_glyphs = 0
    for s in SENTENCES:
        times = []
        for _ in range(repeats):
            buf = hb.Buffer()
            buf.add_str(s)
            buf.guess_segment_properties()
            t0 = time.perf_counter()
            hb.shape(font, buf)
            times.append((time.perf_counter() - t0) * 1e6)  # microseconds
        total_glyphs += len(buf.glyph_infos)
        per_sentence.append(statistics.median(times))
    chars = sum(len(s) for s in SENTENCES)
    return {
        "face_load_ms": round(load_ms, 3),
        "first_shape_ms": round(first_shape_ms, 3),
        "median_shape_us_per_sentence": round(statistics.median(per_sentence), 1),
        "total_shape_us": round(sum(per_sentence), 1),
        "us_per_char": round(sum(per_sentence) / chars, 2),
        "chars": chars,
    }


def validate(font_path: str) -> dict:
    out = {"fonttools_open": False, "ots": None}
    try:
        from fontTools.ttLib import TTFont

        f = TTFont(font_path)
        f["GSUB"].table  # force decompile of the layout table
        _ = f["glyf"]["  "] if False else None
        out["fonttools_open"] = True
        out["num_glyphs"] = f["maxp"].numGlyphs
    except Exception as e:  # pragma: no cover
        out["fonttools_error"] = f"{type(e).__name__}: {e}"
    # OpenType Sanitizer: the validator Chrome and Firefox actually run fonts
    # through before using them, so a PASS here is a real browser precondition.
    try:
        import ots

        r = subprocess.run([ots.OTS_SANITIZE, font_path, "/dev/null"],
                           capture_output=True, text=True, timeout=600)
        msg = (r.stdout + r.stderr).strip()
        out["ots"] = "PASS" if r.returncode == 0 else f"FAIL: {msg[-500:]}"
        out["ots_messages"] = msg[-2000:]
    except ImportError:
        out["ots"] = "not installed"
    except subprocess.TimeoutExpired:
        out["ots"] = "timeout"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", default="data/normalized/rules.jsonl")
    ap.add_argument("--sizes", default="1000,10000,25000,50000,100000,200000,0")
    ap.add_argument("--out", default="benchmarks/results.json")
    ap.add_argument("--keep-fonts", action="store_true")
    args = ap.parse_args()

    all_rules = rules_mod.load(args.rules)
    ordered = sorted(all_rules, key=lambda r: (-r.pri, -len(r.seq), r.seq))
    print(f"[bench] {len(ordered)} rules available")

    results = []
    for spec in args.sizes.split(","):
        n = int(spec)
        subset = ordered if n == 0 else ordered[:n]
        label = "all" if n == 0 else str(n)
        path = f"build/bench_{label}.ttf"
        gc.collect()
        rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        info = build_mod.build_font(subset, out_path=path,
                                    family=f"YomiBench{label}", verbose=False)
        rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        info["peak_rss_mb"] = round(rss_after / (1024 * 1024), 1)
        info["rss_delta_mb"] = round((rss_after - rss_before) / (1024 * 1024), 1)
        info.update(validate(path))
        info["shaping"] = shape_bench(path)
        info["label"] = label
        results.append(info)
        print(
            f"[bench] {label:>7s} rules={info['rules_compiled']:>7d} "
            f"glyphs={info['glyphs']:>6d} ruby={info['ruby_glyphs']:>5d} "
            f"font={info['font_bytes']/1e6:6.2f}MB gsub={info['gsub_bytes']/1e6:6.2f}MB "
            f"build={info['build_seconds']:6.1f}s "
            f"shape={info['shaping']['us_per_char']:6.2f}us/char "
            f"load={info['shaping']['face_load_ms']:.2f}ms "
            f"ots={info['ots']}"
        )
        if not args.keep_fonts and label != "all":
            os.remove(path)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(results, open(args.out, "w"), indent=1)
    print(f"[bench] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
