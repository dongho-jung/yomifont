#!/usr/bin/env python3
"""Does every emitted rule actually spell the reading it came from?

    PYTHONPATH=src ./scripts/audit_readings.py

A rule is a promise: *this* surface, read *this* way.  What the reader sees is
not the rule's groups alone -- it is the groups interleaved with the surface
characters the groups do not cover:

    一ヶ月  groups ((0,1,'いっ'), (2,1,'げつ'))
            reader sees  いっ + ヶ + げつ

so the displayed reading is `いっヶげつ`, and the `か` of いっかげつ has
silently disappeared.  That is a wrong reading, not an abstention, and it is
invisible to any test that only checks the groups.

This script reconstructs the displayed reading for every rule and checks it
against the readings the lexicon actually attests for that surface.  A rule
whose displayed reading is attested nowhere is emitting something no dictionary
supports.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from yomifont import lexicon, rules as rules_mod  # noqa: E402
from yomifont.kana import is_kana, kata_to_hira, normalize_reading  # noqa: E402


def displayed_reading(seq: str, groups) -> str:
    """What the reader actually sees: ruby where there is ruby, surface where not."""
    out: list[str] = []
    pos = 0
    for start, length, reading in sorted(groups):
        out.append(seq[pos:start])
        out.append(reading)
        pos = start + length
    out.append(seq[pos:])
    return kata_to_hira("".join(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", default="data/normalized/rules.jsonl")
    ap.add_argument("--lexicon", default="data/normalized/lexicon.jsonl")
    ap.add_argument("--names", default="data/normalized/names.jsonl")
    ap.add_argument("--report", default="data/normalized/reading_audit.json")
    ap.add_argument("--show", type=int, default=25)
    args = ap.parse_args()

    attested: dict[str, set[str]] = defaultdict(set)
    for path in (args.lexicon, args.names):
        if not os.path.exists(path):
            continue
        for e in lexicon.load(path):
            attested[e.surface].add(normalize_reading(e.reading))
    print(f"[audit] {len(attested)} surfaces with attested readings")

    rs = rules_mod.load(args.rules)
    bad: list[dict] = []
    blocks = 0
    by_origin: Counter = Counter()
    for r in rs:
        if not r.groups:
            blocks += 1
            continue
        shown = displayed_reading(r.seq, r.groups)
        known = attested.get(r.seq) or attested.get(r.src) or set()
        if shown in known:
            continue
        # A stem rule is the lemma with its inflectional tail replaced, so its
        # displayed reading legitimately diverges from the lemma *after* the
        # last ruby group -- 取っ shows とっ against the lemma's とる. What must
        # still hold is that everything up to and including the ruby agrees
        # with the lemma; a divergence inside the ruby is a real error.
        head = displayed_reading(r.seq, r.groups)
        last = max(s + ln for s, ln, _ in r.groups)
        ruby_end = len(displayed_reading(r.seq[:last], [g for g in r.groups]))
        head = head[:ruby_end]
        if any(k.startswith(head) for k in known | attested.get(r.src, set())):
            continue
        bad.append({"seq": r.seq, "shown": shown, "attested": sorted(known),
                    "origin": r.origin, "src": r.src,
                    "groups": [list(g) for g in r.groups]})
        by_origin[r.origin] += 1

    total = len(rs) - blocks
    print(f"[audit] {total} ruby-emitting rules, {blocks} block rules")
    print(f"[audit] {len(bad)} rules display a reading the lexicon does not attest "
          f"({100 * len(bad) / max(total, 1):.3f} %)")
    if by_origin:
        print(f"[audit] by origin: {dict(by_origin)}")

    # group the failures by what the surface has in it, which is what points at
    # the mechanism rather than at individual words
    def signature(row: dict) -> str:
        s = row["seq"]
        covered = set()
        for st, ln, _ in row["groups"]:
            covered.update(range(st, st + ln))
        loose = [s[i] for i in range(len(s)) if i not in covered]
        return "".join(sorted(set(c for c in loose if is_kana(c)))) or "(none)"

    sigs = Counter(signature(b) for b in bad)
    print("\n[audit] uncovered kana in the failing surfaces, most common first:")
    for sig, n in sigs.most_common(15):
        print(f"          {sig!r:<12} {n}")

    print(f"\n[audit] first {args.show}:")
    for b in bad[:args.show]:
        print(f"   {b['seq']:<12} shows {b['shown']!r:<20} "
              f"attested {b['attested']}  origin={b['origin']}")

    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    json.dump({"total_ruby_rules": total, "block_rules": blocks,
               "unattested": len(bad), "by_origin": dict(by_origin),
               "signatures": dict(sigs), "rows": bad[:2000]},
              open(args.report, "w"), ensure_ascii=False, indent=1)
    print(f"\n[audit] wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
