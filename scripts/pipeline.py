#!/usr/bin/env python3
"""End-to-end YomiFont build (Phase 2).

    ./scripts/pipeline.py                    # core build, JMdict only
    ./scripts/pipeline.py --names            # + JMnedict proper names
    ./scripts/pipeline.py --limit 50000      # smaller web build

Stages: JMdict (+JMnedict) -> lexical IR -> safety classifier -> alignment
        -> rules -> GSUB -> .ttf
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
from yomifont import explicit  # noqa: E402
from yomifont import jmdict, jmnedict, lexicon, rules as rules_mod, safety  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jmdict", default="data/raw/JMdict_e.gz")
    ap.add_argument("--jmnedict", default="data/raw/JMnedict.xml.gz")
    ap.add_argument("--lexicon", default="data/normalized/lexicon.jsonl")
    ap.add_argument("--names-ir", default="data/normalized/names.jsonl")
    ap.add_argument("--rules", default="data/normalized/rules.jsonl")
    ap.add_argument("--base", default=build_mod.DEFAULT_BASE)
    ap.add_argument("--out", default="dist/YomiFont-Regular.ttf")
    ap.add_argument("--family", default="YomiFont")
    ap.add_argument("--names", action="store_true",
                    help="include JMnedict proper names (+433k rules)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reparse", action="store_true")
    ap.add_argument("--stats-out", default="")
    ap.add_argument("--no-explicit", action="store_true",
                    help="leave out Explicit Ruby (｜BASE（RUBY）)")
    ap.add_argument("--explicit-base", type=int, default=explicit.DEFAULT_LIMITS.base,
                    help="maximum base characters in an explicit expression")
    ap.add_argument("--explicit-ruby", type=int, default=explicit.DEFAULT_LIMITS.ruby,
                    help="maximum ruby characters in an explicit expression")
    ap.add_argument("--explicit-grid", type=int, default=explicit.GRID,
                    help="explicit-ruby placement lattice, font units")
    ap.add_argument("--explicit-latin", action="store_true",
                    help="also allow Latin and digits *inside* the ruby")
    args = ap.parse_args()

    if args.reparse or not os.path.exists(args.lexicon):
        lexicon.save(jmdict.dedupe(jmdict.parse(args.jmdict)), args.lexicon)
    ents = lexicon.load(args.lexicon)
    print(f"[lexicon] {len(ents)} JMdict (surface, reading) pairs")

    if args.names:
        if args.reparse or not os.path.exists(args.names_ir):
            lexicon.save(jmnedict.parse(args.jmnedict), args.names_ir)
        names = lexicon.load(args.names_ir)
        ents = ents + names
        print(f"[lexicon] + {len(names)} JMnedict pairs")

    verdicts = safety.classify(ents)
    rep = safety.report(verdicts, ents)
    print(f"[safety]  {rep['safe_unique']} safe / {rep['ambiguous']} ambiguous "
          f"of {rep['surfaces_considered']} surfaces ({rep['safe_pct']}% safe)")

    stats: dict = {}
    rs = rules_mod.build_rules(ents, verdicts, stats)
    c = stats["counts"]
    print(f"[rules]   {len(rs)} rules  "
          f"(lex {c.get('lex_rules',0)}, stem {c.get('stem_rules',0)}, "
          f"suru {c.get('suru_rules',0)}, name {c.get('name_rules',0)}, "
          f"block {c.get('final_block_rules',0)})")
    print(f"[rules]   abstained: {c.get('blocked_ambiguous_surface',0)} ambiguous "
          f"surfaces, {c.get('blocked_conflicting_derivations',0)} conflicting "
          f"derivations, {c.get('blocked_lex_vs_derived',0)} lex-vs-derived, "
          f"{c.get('skip_single_kanji',0)} single kanji, "
          f"{c.get('UNSAFE_ALIGNMENT',0)} unalignable")
    rules_mod.save(rs, args.rules)

    if args.limit:
        rs = sorted(rs, key=lambda r: (-len(r.seq), r.seq))[: args.limit]
        print(f"[rules]   truncated to {len(rs)}")

    limits = None if args.no_explicit else explicit.Limits(args.explicit_base,
                                                           args.explicit_ruby)
    info = build_mod.build_font(rs, base_path=args.base, out_path=args.out,
                                family=args.family, explicit=limits,
                                explicit_grid=args.explicit_grid,
                                explicit_latin=args.explicit_latin)
    info["rule_stats"] = c
    info["safety"] = rep
    if args.stats_out:
        json.dump(info, open(args.stats_out, "w"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
