#!/usr/bin/env python3
"""End-to-end YomiFont build.

    ./scripts/pipeline.py                 # full build
    ./scripts/pipeline.py --limit 10000   # smaller rule set
    ./scripts/pipeline.py --no-priors     # JMdict only, no UniDic

Stages: JMdict -> lexical IR -> alignment -> rules -> GSUB -> .ttf
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)

from yomifont import build as build_mod  # noqa: E402
from yomifont import jmdict, rules as rules_mod  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jmdict", default="data/raw/JMdict_e.gz")
    ap.add_argument("--lexicon", default="data/normalized/lexicon.jsonl")
    ap.add_argument("--rules", default="data/normalized/rules.jsonl")
    ap.add_argument("--priors", default="data/normalized/priors.json")
    ap.add_argument("--overrides", default="data/overrides.tsv")
    ap.add_argument("--base", default=build_mod.DEFAULT_BASE)
    ap.add_argument("--out", default="dist/YomiFont-Regular.ttf")
    ap.add_argument("--family", default="YomiFont")
    ap.add_argument("--limit", type=int, default=0, help="keep only the N highest-priority rules")
    ap.add_argument("--no-priors", action="store_true")
    ap.add_argument("--no-overrides", action="store_true")
    ap.add_argument("--abstain-margin", type=float, default=0.0,
                    help="drop a rule when the runner-up reading is within this "
                         "ratio of the winner (1.05 = near-ties, 0 = never)")
    ap.add_argument("--no-lone-kanji", action="store_true",
                    help="skip the single-kanji fallbacks that make Blink work")
    ap.add_argument("--reparse", action="store_true", help="re-parse JMdict even if cached")
    ap.add_argument("--stats-out", default="")
    args = ap.parse_args()

    if args.reparse or not os.path.exists(args.lexicon):
        ents = jmdict.dedupe(jmdict.parse(args.jmdict))
        jmdict.save(ents, args.lexicon)
    else:
        ents = jmdict.load(args.lexicon)
        print(f"[jmdict] {len(ents)} cached (surface, reading) pairs")

    priors = {}
    if not args.no_priors:
        from build_priors import load_priors

        priors = load_priors(args.priors)
        print(f"[priors] {len(priors)} corpus priors")
    overrides = {} if args.no_overrides else rules_mod.load_overrides(args.overrides)

    stats: dict = {}
    rs = rules_mod.build_rules(ents, stats=stats, priors=priors, overrides=overrides,
                               abstain_margin=args.abstain_margin)
    if not args.no_priors and not args.no_lone_kanji:
        from build_priors import load_priors as _lp

        lone = _lp(args.priors.replace(".json", "_lone_kanji.json"))
        if lone:
            rs = rules_mod.add_lone_kanji_fallbacks(rs, lone, stats)
            c = stats["counts"]
            print(f"[rules]  lone-kanji fallbacks: "
                  f"{c.get('lone_kanji_added',0)} added, "
                  f"{c.get('lone_kanji_replaced',0)} replaced, "
                  f"{c.get('lone_kanji_unchanged',0)} unchanged")
    print(f"[rules]  {len(rs)} rules")
    rules_mod.save(rs, args.rules)

    if args.limit:
        rs = sorted(rs, key=lambda r: (-r.pri, -len(r.seq)))[: args.limit]
        print(f"[rules]  truncated to {len(rs)}")

    info = build_mod.build_font(rs, base_path=args.base, out_path=args.out,
                                family=args.family)
    info["rule_stats"] = stats["counts"]
    if args.stats_out:
        json.dump(info, open(args.stats_out, "w"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
