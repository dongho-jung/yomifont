#!/usr/bin/env python3
"""Derive (surface, reading) frequency priors from a corpus using UniDic.

This is the OPTIONAL secondary resource described in the project brief.  JMdict
alone cannot rank 中 -> なか above 中 -> うち, because both are ordinary noun
entries; a corpus can.  The output is a small JSON table of priority bonuses
that the rule builder adds before conflict resolution.

    ./scripts/build_priors.py --train 0:120000 --out data/normalized/priors.json

Only counts are derived, never readings themselves: a (surface, reading) pair
that JMdict does not have will never appear in the font.  The evaluation split
must be disjoint from --train or the accuracy number is meaningless.

UniDic (unidic-lite) is BSD/LGPL/GPL tri-licensed and is a *build-time* tool
only; nothing from it is embedded in the font.  See docs/licensing.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from yomifont import jmdict  # noqa: E402
from yomifont.alignment import AlignError, align  # noqa: E402
from yomifont.kana import is_kana, is_kanji, kata_to_hira  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate import load_corpus  # noqa: E402

# Priors are stored as raw corpus counts and turned into priorities by the rule
# builder.  Corpus evidence is treated as a *tier* above JMdict's editorial
# priority rather than as a bounded bonus added to it: two hand-tuned weights
# summed together could never separate 行く (いく, ~2.5k hits) from
# 行う (おこなう, ~250 hits) once both saturated the bonus cap.
#
# See yomifont.rules.prior_priority for the count -> priority mapping.


def _count_lone_kanji(surface: str, reading: str, whole: Counter, stem: Counter) -> None:
    """Count kanji that form a one-character Han run inside `surface`.

    The reading assigned to that kanji comes from the same okurigana alignment
    the compiler uses, so the counts are directly comparable with the rules.

    No JMdict filter is applied here: 行 in 行った is read い, but JMdict has no
    single-character 行/い entry, so filtering against it would throw away
    exactly the cases this table exists to fix.  The rule builder does the
    safety check instead -- it only adopts a reading that YomiFont already
    assigns to that character somewhere else, so nothing is invented.
    """
    if not any(is_kanji(c) for c in surface):
        return
    try:
        groups = align(surface, reading)
    except AlignError:
        return
    for g in groups:
        if g.length != 1 or not is_kanji(surface[g.start]):
            continue
        before_ok = g.start == 0 or not is_kanji(surface[g.start - 1])
        after_ok = g.start + 1 == len(surface) or not is_kanji(surface[g.start + 1])
        if not (before_ok and after_ok):
            continue
        # Two very different situations, so they are counted separately:
        #   whole  the kanji IS the token (noun 話 / はなし).  Every engine
        #          reaches the single-character rule here.
        #   stem   the kanji is a lone Han run inside a longer token
        #          (話し / はなし).  Only Blink reaches the single-character
        #          rule here; elsewhere a longer stem rule matches first.
        (whole if len(surface) == 1 else stem)[(surface[g.start], g.reading)] += 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="0:120000", help="sentence slice a:b")
    ap.add_argument("--lexicon", default="data/normalized/lexicon.jsonl")
    ap.add_argument("--out", default="data/normalized/priors.json")
    args = ap.parse_args()

    import fugashi
    import unidic_lite

    a, b = (int(x) for x in args.train.split(":"))
    sentences = load_corpus(b)[a:b]
    tagger = fugashi.Tagger("-d " + unidic_lite.DICDIR)

    # only pairs JMdict already knows are eligible for a bonus
    allowed: set[tuple[str, str]] = set()
    surfaces: set[str] = set()
    for e in jmdict.load(args.lexicon):
        allowed.add((e.surface, e.reading))
        surfaces.add(e.surface)

    counts: Counter = Counter()
    # (kanji, reading) counts for kanji that stand alone between kana inside a
    # token -- 行 in 行った, 分 in 分かりました.  This is the distribution the
    # single-character fallback rule actually faces, and it is the *only* thing
    # Blink can see for such a kanji, because Chrome itemises text into script
    # runs before shaping and the okurigana ends up in a different run.
    lone_whole: Counter = Counter()
    lone_stem: Counter = Counter()
    for sent in sentences:
        for tok in tagger(sent):
            f = tok.feature
            kana_r = getattr(f, "kana", None)
            if kana_r:
                _count_lone_kanji(tok.surface, kata_to_hira(kana_r),
                                  lone_whole, lone_stem)
            # Surface level: settles noun homographs (中 -> なか vs うち).
            surf = tok.surface
            kana = getattr(f, "kana", None)
            if kana and any(is_kanji(c) for c in surf) and surf in surfaces:
                pair = (surf, kata_to_hira(kana))
                if pair in allowed:
                    counts[pair] += 1
            # Lemma level: settles which *verb* an inflected form belongs to.
            # 行っ is not a JMdict surface, so only (行く, いく) vs
            # (行う, おこなう) can be ranked -- and the rule builder propagates
            # that ranking into the stem rules it derives from those entries.
            base = getattr(f, "orthBase", None) or getattr(f, "lemma", None)
            lform = getattr(f, "lForm", None)
            if base and lform and any(is_kanji(c) for c in base) and base in surfaces:
                pair = (base, kata_to_hira(lform))
                if pair in allowed:
                    counts[pair] += 1

    by_surface = {surf for surf, _ in counts}

    priors = {surf + "\t" + read: n for (surf, read), n in counts.items()}
    lone_out = {}
    for (k, r), n in lone_whole.items():
        lone_out[k + "\t" + r] = [n, 0]
    for (k, r), n in lone_stem.items():
        lone_out.setdefault(k + "\t" + r, [0, 0])[1] = n

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(priors, open(args.out, "w"), ensure_ascii=False)
    lone_path = args.out.replace(".json", "_lone_kanji.json")
    json.dump(lone_out, open(lone_path, "w"), ensure_ascii=False)
    print(f"[priors] {len(lone_out)} lone-kanji priors -> {lone_path}")
    print(f"[priors] {len(sentences)} training sentences -> {len(priors)} priors "
          f"over {len(by_surface)} surfaces  ({os.path.getsize(args.out)/1e3:.0f} kB)")
    return 0


def load_priors(path: str) -> dict[tuple[str, str], int]:
    if not os.path.exists(path):
        return {}
    raw = json.load(open(path))
    return {tuple(k.split("\t")): v for k, v in raw.items()}


if __name__ == "__main__":
    raise SystemExit(main())
