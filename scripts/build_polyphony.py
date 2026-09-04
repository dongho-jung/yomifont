#!/usr/bin/env python3
"""Surfaces a corpus shows reading more than one way -- so the font abstains.

    ./scripts/build_polyphony.py --train 20000:150000

JMdict is the authority on *which* readings exist, and it is good at it. What
it is not reliable about is whether the reading it lists is the *only* one: it
has one entry for 居る with one reading おる, one for 弾ける with はじける, one
for 時々 with ときどき. Running text disagrees -- いる, ひける, じじ -- and
those are exactly the wrong readings the evaluation keeps finding, every one of
them classified SAFE_UNIQUE because the lexicon really does list one reading.

So: tokenise a corpus slice, record every reading each surface is actually seen
with, and mark a surface polyphonic when it is seen with more than one. The
rule builder then abstains on it.

This uses the corpus strictly to *remove* rules. No reading is ever taken from
it -- a (surface, reading) pair the lexicon does not have can never reach the
font -- so this is morphology validation, not a corpus fallback. The slice must
be disjoint from the evaluation split or the resulting precision is circular.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)

from yomifont.kana import is_kanji, kata_to_hira  # noqa: E402

from evaluate import load_corpus  # noqa: E402

# A reading seen once in 130,000 sentences is as likely to be a tagger error as
# a real alternative, and abstaining on it would cost coverage for nothing.
MIN_HITS = 2
# ...unless the surface is common, where even a couple of hits is real signal.
MIN_SHARE = 0.02


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="20000:150000", help="sentence slice a:b")
    ap.add_argument("--out", default="data/normalized/polyphony.json")
    ap.add_argument("--min-hits", type=int, default=MIN_HITS)
    args = ap.parse_args()

    import fugashi
    import unidic_lite

    tagger = fugashi.Tagger("-d " + unidic_lite.DICDIR)
    a, b = (int(x) for x in args.train.split(":"))
    sentences = load_corpus(b)[a:b]
    print(f"[poly] {len(sentences)} training sentences ({a}:{b})")

    seen: dict[str, Counter] = defaultdict(Counter)
    for s in sentences:
        for tok in tagger(s):
            surface = tok.surface
            if not any(is_kanji(c) for c in surface):
                continue
            kana = getattr(tok.feature, "kana", None) or getattr(tok.feature, "pron", None)
            if not kana or kana == "*":
                continue
            seen[surface][kata_to_hira(kana)] += 1

    # Emit the whole observed table, not just the surfaces read two ways.
    # "Read two ways in the corpus" turned out to be the wrong test: the corpus
    # shows 居る only as いる and 弾ける only as ひける -- one reading each, but
    # not the one the lexicon lists. What makes a rule unsafe is that the
    # corpus *contradicts* it, which only the rule builder can check.
    poly = {s: dict(c.most_common()) for s, c in seen.items()
            if sum(c.values()) >= args.min_hits}
    multi = sum(1 for c in seen.values() if len(c) > 1)
    print(f"[poly] {len(seen)} kanji-bearing surfaces observed, "
          f"{multi} read more than one way, {len(poly)} kept "
          f"(>= {args.min_hits} hits)")
    for s in ["居る", "弾ける", "時々", "下品", "入りかけ", "行った", "市場", "東京"]:
        if s in seen:
            print(f"    {s:<8} {dict(seen[s].most_common(4))}"
                  f"{'  -> polyphonic' if s in poly else ''}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    json.dump(poly, open(args.out, "w"), ensure_ascii=False)
    print(f"[poly] wrote {args.out}")
    return 0


def load_polyphony(path: str) -> dict[str, list[str]]:
    if not path or not os.path.exists(path):
        return {}
    return json.load(open(path, encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
