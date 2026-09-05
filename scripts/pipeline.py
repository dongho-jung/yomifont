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
    ap.add_argument("--names", default="place",
                    choices=("none", "admin", "place", "all"),
                    help="which JMnedict proper names to admit. 'admin' is "
                         "place-like names ending in an administrative suffix "
                         "(東京都, 新宿区, ...). 'place' is every place-like "
                         "name, pruned to the lookup budget. 'all' does not fit.")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reparse", action="store_true")
    ap.add_argument("--stats-out", default="")
    ap.add_argument("--polyphony", default="data/normalized/polyphony.json",
                    help="corpus reading table from build_polyphony.py; used "
                         "only to drop rules the corpus contradicts, never as "
                         "a source of readings")
    ap.add_argument("--minimal-repertoire", action="store_true",
                    help="only include kanji the rules actually use, instead of "
                         "everything the base font can draw. This is the size "
                         "knob -- the extra outlines are most of the file.")
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

    if args.polyphony and os.path.exists(args.polyphony):
        safety.NAME_CORPUS = json.load(open(args.polyphony, encoding="utf-8"))
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
        rs = rules_mod.fit_lookup_budget(rs, safety.NAME_CORPUS, stats=c)
        print(f"[names]   {c.get('name_rules_dropped_no_budget', 0)} name rules "
              f"dropped for lookup budget; projected "
              f"{c.get('ms_lookups_projected')} MultipleSubst lookups")
        rs = rules_mod.block_contradicted_names(rs, known, c)
        print(f"[names]   {c.get('name_blocks', 0)} uncarried names blocked "
              f"because a shorter rule would misread them")

    observed = {}
    if args.polyphony and os.path.exists(args.polyphony):
        observed = json.load(open(args.polyphony, encoding="utf-8"))
        before = len(rs)
        # JMdict only: see drop_corpus_contradicted. Admitting name readings
        # here silently disarms the filter for exactly the surfaces it exists
        # for (上野 こうずけ vs うえの).
        lex_readings: dict = {}
        for e in ents:
            if e.source == "jmdict":
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

    info = build_mod.build_font(rs, base_path=args.base, out_path=args.out,
                                family=args.family,
                                full_repertoire=not args.minimal_repertoire)
    info["rule_stats"] = c
    info["safety"] = rep
    if args.stats_out:
        json.dump(info, open(args.stats_out, "w"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
