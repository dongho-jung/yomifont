#!/usr/bin/env python3
"""Measure YomiFont reading accuracy against UniDic on real Japanese text.

UniDic (via fugashi) is used ONLY as an evaluation oracle at build time; none of
its data ends up in the font.  It gives a contextual gold reading for every
token in a corpus -- exactly the thing a font-level system cannot infer.

    ./scripts/evaluate.py [--limit N] [--rules PATH] [--report PATH]

Comparison is span-aligned: YomiFont's match spans and UniDic's token spans do
not have to agree one-to-one (誕生日 as one rule vs 誕生 + 日 as two tokens is
not an error), so a match is scored whenever its span starts and ends on token
boundaries, against the concatenated gold reading of the tokens it covers.

Metrics
-------
    coverage   kanji-bearing tokens that received any ruby
    correct    scored spans whose reading matched gold
    wrong      scored spans whose reading differed
    unaligned  spans that could not be lined up with token boundaries
"""
from __future__ import annotations

import argparse
import bz2
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from yomifont import rules as rules_mod  # noqa: E402
from yomifont.engine import RuleIndex  # noqa: E402
from yomifont.alignment import AlignError, align  # noqa: E402
from yomifont.kana import is_kanji, kata_to_hira  # noqa: E402


def subtoken_gold(sent, s, e, toks):
    """Gold reading for a span that lies strictly inside one token.

    Blink shapes each Han run alone, so a match span is often just 行 inside
    the token 行った.  Scoring those as "unscorable" would make the Blink
    numbers meaningless, so we run the same okurigana alignment on the token
    and look for a ruby group with exactly this span.
    """
    for ts, te, kana, _ in toks:
        if ts <= s and e <= te and (ts, te) != (s, e):
            try:
                groups = align(sent[ts:te], kana)
            except AlignError:
                return None
            for g in groups:
                if ts + g.start == s and g.length == e - s:
                    return g.reading
            return None
    return None

CORPUS = "data/raw/jpn_sentences.tsv"


def load_corpus(limit: int | None) -> list[str]:
    path = CORPUS if os.path.exists(CORPUS) else CORPUS + ".bz2"
    opener = bz2.open if path.endswith(".bz2") else open
    out = []
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3:
                out.append(parts[2])
            if limit and len(out) >= limit:
                break
    return out


def gold_tokens(tagger, sent: str):
    """[(start, end, kana_reading, lemma_reading)] over the sentence."""
    out = []
    pos = 0
    for tok in tagger(sent):
        surf = tok.surface
        start = sent.find(surf, pos)
        if start < 0:
            continue
        pos = start + len(surf)
        kana = getattr(tok.feature, "kana", None) or ""
        lform = getattr(tok.feature, "lForm", None) or ""
        out.append((start, pos, kata_to_hira(kana) if kana else surf,
                    kata_to_hira(lform) if lform else ""))
    return out


def match_reading(text: str, m) -> str:
    seg = text[m.start : m.start + m.length]
    parts = []
    last = 0
    for gs, gl, rd in m.groups:
        parts.append(seg[last:gs])
        parts.append(rd)
        last = gs + gl
    parts.append(seg[last:])
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20000)
    ap.add_argument("--rules", default="data/normalized/rules.jsonl")
    ap.add_argument("--report", default="data/normalized/eval_report.json")
    ap.add_argument("--show", type=int, default=25)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--segmentation", choices=["none", "script"], default="none",
                    help="'script' models Blink: each Han/Kana run shaped alone")
    args = ap.parse_args()

    import fugashi
    import unidic_lite

    tagger = fugashi.Tagger("-d " + unidic_lite.DICDIR)
    rs = rules_mod.load(args.rules)
    idx = RuleIndex(rs)
    sentences = load_corpus(args.limit)

    # Every reading JMdict attests for a surface.  Used to split disagreements
    # into "we chose a different legitimate reading" and "we produced a reading
    # that does not exist for this word", which are very different defects.
    from yomifont import jmdict as jmdict_mod

    attested: dict[str, set[str]] = {}
    for e in jmdict_mod.load("data/normalized/lexicon.jsonl"):
        attested.setdefault(e.surface, set()).add(e.reading)

    # Spans whose reading we deliberately override away from UniDic's lexeme
    # convention (私 -> わたし, not ワタクシ).  These are counted separately:
    # scoring them as errors would penalise the project for a choice it made on
    # purpose, and scoring them as correct would hide it.
    overrides = rules_mod.load_overrides("data/overrides.tsv")

    stat = Counter()
    wrong_by_surface: Counter = Counter()
    unaligned_examples = []
    uncovered = Counter()

    apply_fn = idx.apply_segmented if args.segmentation == "script" else idx.apply
    for sent in sentences:
        matches = apply_fn(sent)
        toks = gold_tokens(tagger, sent)
        starts = {t[0] for t in toks}
        ends = {t[1] for t in toks}

        # --- coverage over kanji-bearing tokens
        covered_chars = set()
        for m in matches:
            covered_chars.update(range(m.start, m.start + m.length))
        for s, e, _, _ in toks:
            if not any(is_kanji(c) for c in sent[s:e]):
                continue
            stat["kanji_tokens"] += 1
            if any(i in covered_chars for i in range(s, e)):
                stat["kanji_tokens_with_ruby"] += 1
            else:
                uncovered[sent[s:e]] += 1

        # --- token-level outcome: the metric a reader actually experiences.
        # Span-level accuracy alone is misleading, because adding a fallback
        # rule moves tokens from "no ruby" (unscored) into "scored", which
        # lowers span accuracy while making the font strictly more useful.
        span_verdict: dict[int, str] = {}

        # --- accuracy over match spans
        for m in matches:
            s, e = m.start, m.start + m.length
            if not any(is_kanji(c) for c in sent[s:e]):
                continue
            stat["spans"] += 1
            if s not in starts or e not in ends:
                sub = subtoken_gold(sent, s, e, toks)
                if sub is not None:
                    got = kata_to_hira(match_reading(sent, m))
                    if got == sub:
                        stat["correct"] += 1
                        for i in range(s, e):
                            span_verdict[i] = "correct"
                    elif sent[s:e] in overrides and got == overrides[sent[s:e]]:
                        stat["deliberate_override"] += 1
                        for i in range(s, e):
                            span_verdict[i] = "override"
                    elif got in attested.get(sent[s:e], ()):
                        stat["wrong_but_attested"] += 1
                        for i in range(s, e):
                            span_verdict[i] = "wrong"
                        wrong_by_surface[(sent[s:e], sub, got)] += 1
                    else:
                        stat["wrong_unattested"] += 1
                        for i in range(s, e):
                            span_verdict[i] = "wrong"
                        wrong_by_surface[(sent[s:e], sub, got)] += 1
                    continue
                stat["unaligned"] += 1
                for i in range(s, e):
                    span_verdict[i] = "unaligned"
                if len(unaligned_examples) < args.show:
                    unaligned_examples.append(
                        {"span": sent[s:e], "sent": sent[:44], "rule": m.rule.seq}
                    )
                continue
            inner = [t for t in toks if t[0] >= s and t[1] <= e]
            gold_kana = "".join(t[2] for t in inner)
            gold_lform = "".join(t[3] or t[2] for t in inner)
            # fold katakana on both sides: フランス語 legitimately keeps its
            # katakana in the surface, UniDic reports ふらんすご
            got = kata_to_hira(match_reading(sent, m))
            if got == gold_kana or got == gold_lform:
                stat["correct"] += 1
                for i in range(s, e):
                    span_verdict[i] = "correct"
            elif sent[s:e] in overrides and got == overrides[sent[s:e]]:
                stat["deliberate_override"] += 1
                for i in range(s, e):
                    span_verdict[i] = "override"
            elif got in attested.get(sent[s:e], ()):
                # both readings are real; the oracle and the font just picked
                # different ones (私 -> わたし vs わたくし)
                stat["wrong_but_attested"] += 1
                for i in range(s, e):
                    span_verdict[i] = "wrong"
                wrong_by_surface[(sent[s:e], gold_kana, got)] += 1
            else:
                stat["wrong_unattested"] += 1
                for i in range(s, e):
                    span_verdict[i] = "wrong"
                wrong_by_surface[(sent[s:e], gold_kana, got)] += 1

        for s_, e_, _, _ in toks:
            if not any(is_kanji(c) for c in sent[s_:e_]):
                continue
            vs = {span_verdict.get(i) for i in range(s_, e_)} - {None}
            if "wrong" in vs:
                stat["tok_wrong"] += 1
            elif "correct" in vs or "override" in vs:
                stat["tok_correct"] += 1
            elif "unaligned" in vs:
                stat["tok_unaligned"] += 1
            else:
                stat["tok_no_ruby"] += 1

    stat["wrong"] = stat["wrong_but_attested"] + stat["wrong_unattested"]
    scored = stat["correct"] + stat["wrong"] + stat["deliberate_override"]
    if not args.quiet:
        print(f"[eval] {len(rs)} rules / {len(idx.buckets)} first chars / "
              f"{len(sentences)} sentences / segmentation={args.segmentation}")
        print(f"[eval] kanji-bearing tokens        {stat['kanji_tokens']}")
        print(f"       with ruby (coverage)        {stat['kanji_tokens_with_ruby']} "
              f"({100*stat['kanji_tokens_with_ruby']/max(1,stat['kanji_tokens']):.2f}%)")
        print(f"[eval] ruby spans                  {stat['spans']}")
        print(f"       scored                      {scored}")
        print(f"       correct                     {stat['correct']} "
              f"({100*stat['correct']/max(1,scored):.2f}%)")
        print(f"       wrong                       {stat['wrong']} "
              f"({100*stat['wrong']/max(1,scored):.2f}%)")
        print(f"         .. other attested reading {stat['wrong_but_attested']} "
              f"({100*stat['wrong_but_attested']/max(1,scored):.2f}%)")
        print(f"         .. reading not attested   {stat['wrong_unattested']} "
              f"({100*stat['wrong_unattested']/max(1,scored):.2f}%)")
        print(f"       deliberate override         {stat['deliberate_override']} "
              f"({100*stat['deliberate_override']/max(1,scored):.2f}%)")
        print(f"       unaligned to tokenizer      {stat['unaligned']} "
              f"({100*stat['unaligned']/max(1,stat['spans']):.2f}%)")
        kt = max(1, stat["kanji_tokens"])
        print(f"[eval] TOKEN-LEVEL outcome over {stat['kanji_tokens']} kanji tokens")
        for k, lbl in (("tok_correct", "correct ruby"), ("tok_wrong", "wrong ruby"),
                       ("tok_unaligned", "ruby, unscorable"), ("tok_no_ruby", "no ruby")):
            print(f"       {lbl:<20s} {stat[k]:8d}  {100*stat[k]/kt:6.2f}%")
        print("\n[eval] top wrong readings")
        for (surf, gold, got), n in wrong_by_surface.most_common(args.show):
            print(f"   {n:5d}  {surf:10s} gold={gold:14s} got={got}")
        print("\n[eval] most common uncovered tokens")
        for t, n in uncovered.most_common(args.show):
            print(f"   {n:5d}  {t}")
        print("\n[eval] unaligned examples")
        for e in unaligned_examples[:10]:
            print(f"   rule={e['rule']:10s} span={e['span']:10s} in {e['sent']}")

    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    json.dump(
        {
            "rules": len(rs),
            "segmentation": args.segmentation,
            "sentences": len(sentences),
            "stats": dict(stat),
            "accuracy": stat["correct"] / max(1, scored),
            "accuracy_incl_overrides":
                (stat["correct"] + stat["deliberate_override"]) / max(1, scored),
            "accuracy_or_attested_alternative":
                (stat["correct"] + stat["wrong_but_attested"]) / max(1, scored),
            "coverage": stat["kanji_tokens_with_ruby"] / max(1, stat["kanji_tokens"]),
            "token_correct_rate": stat["tok_correct"] / max(1, stat["kanji_tokens"]),
            "token_wrong_rate": stat["tok_wrong"] / max(1, stat["kanji_tokens"]),
            "top_wrong": [
                {"surface": s, "gold": g, "got": t, "n": n}
                for (s, g, t), n in wrong_by_surface.most_common(400)
            ],
            "top_uncovered": [{"token": t, "n": n} for t, n in uncovered.most_common(200)],
        },
        open(args.report, "w"),
        ensure_ascii=False,
        indent=1,
    )
    if args.quiet:
        print(f"tok_correct={100*stat['tok_correct']/max(1,stat['kanji_tokens']):.2f}% "
              f"tok_wrong={100*stat['tok_wrong']/max(1,stat['kanji_tokens']):.2f}% "
              f"acc={100*stat['correct']/max(1,scored):.2f}% "
              f"acc+ovr={100*(stat['correct']+stat['deliberate_override'])/max(1,scored):.2f}% "
              f"cov={100*stat['kanji_tokens_with_ruby']/max(1,stat['kanji_tokens']):.2f}% "
              f"rules={len(rs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
