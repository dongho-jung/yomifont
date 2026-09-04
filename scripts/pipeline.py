#!/usr/bin/env python3
"""End-to-end YomiFont build (Phase 2).

    ./scripts/pipeline.py                    # core build (JMdict + admin places)
    ./scripts/pipeline.py --names none       # JMdict only
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
    ap.add_argument("--names", default="admin",
                    choices=("none", "admin", "place", "all"),
                    help="which JMnedict proper names to admit. 'admin' is "
                         "place-like names ending in an administrative suffix "
                         "(東京都, 新宿区, ...): the subset that fits under the "
                         "LookupList ceiling. 'place'/'all' do not compile.")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reparse", action="store_true")
    ap.add_argument("--stats-out", default="")
    ap.add_argument("--polyphony", default="data/normalized/polyphony.json",
                    help="corpus reading table from build_polyphony.py; used "
                         "only to drop rules the corpus contradicts, never as "
                         "a source of readings")
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
    ap.add_argument("--no-explicit-bases", action="store_true",
                    help="do not widen the kanji repertoire for explicit bases; "
                         "explicit ruby then only works on characters the rules "
                         "already use. This is the size knob -- the extra kanji "
                         "outlines cost far more than the ruby glyphs do.")
    args = ap.parse_args()

    if args.reparse or not os.path.exists(args.lexicon):
        lexicon.save(jmdict.dedupe(jmdict.parse(args.jmdict)), args.lexicon)
    ents = lexicon.load(args.lexicon)
    print(f"[lexicon] {len(ents)} JMdict (surface, reading) pairs")

    if args.names != "none":
        if args.reparse or not os.path.exists(args.names_ir):
            lexicon.save(jmnedict.parse(args.jmnedict), args.names_ir)
        names = lexicon.load(args.names_ir)
        if args.names == "admin":
            names = [e for e in names
                     if jmnedict.is_admin_place(e.surface, e.ntype)]
        elif args.names == "place":
            names = [e for e in names if set(e.ntype) & jmnedict.PLACE_LIKE]
        ents = ents + names
        print(f"[lexicon] + {len(names)} JMnedict pairs ({args.names})")

    # Person names vote but are never rendered. They are what makes 上野, 平野
    # and 陽子 ambiguous -- a personal name is what the text means often enough
    # to matter -- but admitting them as a *source* would add 265k rules of
    # names nobody asked the font to read. So they go to the classifier and not
    # to the rule builder.
    voters = ents
    if args.names != "none" and safety.PERSON_NAMES_VETO:
        person = [e for e in lexicon.load(args.names_ir)
                  if set(e.ntype) & jmnedict.PERSON_LIKE]
        voters = ents + person
        print(f"[lexicon] + {len(person)} person-name entries as competitors only")

    verdicts = safety.classify(voters)
    rep = safety.report(verdicts, voters)
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
    # Names the rule set does not carry, whose composed rendering would
    # contradict their real reading, become abstentions. Block rules share one
    # MultipleSubst output per first glyph, so this costs 0 lookups.
    if args.names != "none":
        known: dict = {}
        for e in lexicon.load(args.names_ir):
            if set(e.ntype) & jmnedict.PLACE_LIKE and e.live:
                known.setdefault(e.surface, set()).add(e.reading)
        rs = rules_mod.block_contradicted_names(rs, known, c)
        print(f"[names]   {c.get('name_blocks', 0)} uncarried names blocked "
              f"because a shorter rule would misread them")

    observed = {}
    if args.polyphony and os.path.exists(args.polyphony):
        observed = json.load(open(args.polyphony, encoding="utf-8"))
        before = len(rs)
        lex_readings: dict = {}
        for e in ents:
            lex_readings.setdefault(e.surface, set()).add(e.reading)
        rs = rules_mod.drop_corpus_contradicted(rs, observed, lex_readings,
                                                stats=c)
        print(f"[corpus]  {c.get('corpus_contradicted', 0)} rules the corpus "
              f"contradicts turned into abstentions "
              f"({len(observed)} surfaces observed)")
    rules_mod.save(rs, args.rules)

    if args.limit:
        rs = sorted(rs, key=lambda r: (-len(r.seq), r.seq))[: args.limit]
        print(f"[rules]   truncated to {len(rs)}")

    limits = None if args.no_explicit else explicit.Limits(args.explicit_base,
                                                           args.explicit_ruby)
    info = build_mod.build_font(rs, base_path=args.base, out_path=args.out,
                                family=args.family, explicit=limits,
                                explicit_grid=args.explicit_grid,
                                explicit_latin=args.explicit_latin,
                                explicit_bases=not args.no_explicit_bases)
    info["rule_stats"] = c
    info["safety"] = rep
    if args.stats_out:
        json.dump(info, open(args.stats_out, "w"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
