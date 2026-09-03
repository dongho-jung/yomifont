#!/usr/bin/env python3
"""Measure YomiFont against UniDic on held-out Japanese text.

Phase 2 metric. The headline number is PRECISION:

    precision = correct ruby / ruby YomiFont actually rendered

Coverage is reported separately and is explicitly allowed to be low. A font
that renders ruby on 78 % of tokens and is never wrong beats one that renders
on 99.9 % and is wrong 8 % of the time.

    ./scripts/evaluate.py [--limit N] [--segmentation none|script]

`--segmentation script` models Blink, which itemises text into script runs
before shaping so no rule can span a Han/Kana boundary.

Every disagreement is written to an error corpus (JSON) with a deterministic
root-cause class, so the "drive incorrect ruby to zero" loop has something to
work on.
"""
from __future__ import annotations

import argparse
import bz2
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from yomifont import lexicon as lexicon_mod  # noqa: E402
from yomifont import rules as rules_mod  # noqa: E402
from yomifont import safety as safety_mod  # noqa: E402
from yomifont.alignment import AlignError, align  # noqa: E402
from yomifont.engine import RuleIndex  # noqa: E402
from yomifont.kana import is_kanji, kata_to_hira  # noqa: E402

CORPUS = "data/raw/jpn_sentences.tsv"

# UniDic reports a lemma-level reading, which differs from what a reader wants
# as furigana for a handful of high-frequency forms. These are oracle
# conventions, not YomiFont errors; they are counted separately rather than
# quietly folded into "correct".
ORACLE_VARIANTS = {
    ("日本", "にっぽん"): "にほん",
    ("日本語", "にっぽんご"): "にほんご",
    ("日本人", "にっぽんじん"): "にほんじん",
    ("富士山", "ふじやま"): "ふじさん",
}


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
    seg = text[m.start: m.start + m.length]
    parts, last = [], 0
    for gs, gl, rd in m.groups:
        parts.append(seg[last:gs])
        parts.append(rd)
        last = gs + gl
    parts.append(seg[last:])
    return "".join(parts)


def subtoken_gold(sent, s, e, toks):
    """Gold reading for a span lying strictly inside one token."""
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


def _classify_error(span, got, gold, m, verdicts, rule) -> str:
    """Deterministic root-cause classes for the error corpus."""
    v = verdicts.get(span)
    if rule is not None and rule.origin == "name":
        return "name_rule_wrong"
    if rule is not None and rule.origin in ("stem", "suru", "irregular"):
        if m.rule.seq != span:
            return "inflection_rule_span_mismatch"
        return "inflection_rule_wrong"
    if v is None:
        return "span_not_a_lexicon_surface"
    if v.safety is safety_mod.Safety.AMBIGUOUS:
        return "ambiguous_should_not_have_fired"
    if got in v.readings:
        return "lexicon_reading_but_context_differs"
    return "lexicon_disagrees_with_oracle"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20000)
    ap.add_argument("--rules", default="data/normalized/rules.jsonl")
    ap.add_argument("--lexicon", default="data/normalized/lexicon.jsonl")
    ap.add_argument("--names", default="data/normalized/names.jsonl")
    ap.add_argument("--report", default="data/normalized/eval_report.json")
    ap.add_argument("--errors", default="data/normalized/error_corpus.json")
    ap.add_argument("--segmentation", choices=["none", "script"], default="none")
    ap.add_argument("--show", type=int, default=25)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    import fugashi
    import unidic_lite

    tagger = fugashi.Tagger("-d " + unidic_lite.DICDIR)
    rs = rules_mod.load(args.rules)
    idx = RuleIndex(rs)
    rule_by_seq = {r.seq: r for r in rs}
    sentences = load_corpus(args.limit)

    ents = lexicon_mod.load(args.lexicon)
    if os.path.exists(args.names):
        ents += lexicon_mod.load(args.names)
    verdicts = safety_mod.classify(ents)
    name_surfaces = {v.surface for v in verdicts.values()
                     if v.sources == ("jmnedict",)}

    stat: Counter = Counter()
    errors: list[dict] = []
    error_kinds: Counter = Counter()
    abstain_reason: Counter = Counter()
    apply_fn = idx.apply_segmented if args.segmentation == "script" else idx.apply

    for sent in sentences:
        matches = apply_fn(sent)
        toks = gold_tokens(tagger, sent)
        starts = {t[0] for t in toks}
        ends = {t[1] for t in toks}
        # A rule with no ruby groups is a BLOCK: it exists to stop a shorter
        # rule from firing on an ambiguous sequence. It is an abstention, not
        # rendered ruby, and must not be scored as either coverage or output.
        matches = [m for m in matches if m.groups]
        covered = set()
        for m in matches:
            covered.update(range(m.start, m.start + m.length))

        # ---- token accounting
        for s, e, kana, _ in toks:
            surf = sent[s:e]
            if not any(is_kanji(c) for c in surf):
                continue
            stat["eligible_tokens"] += 1
            is_name = surf in name_surfaces
            if is_name:
                stat["name_tokens"] += 1
            if any(i in covered for i in range(s, e)):
                stat["tokens_with_ruby"] += 1
                if is_name:
                    stat["name_tokens_with_ruby"] += 1
            else:
                stat["tokens_abstained"] += 1
                v = verdicts.get(surf)
                if v is None:
                    abstain_reason["not_in_lexicon"] += 1
                elif v.safety is safety_mod.Safety.AMBIGUOUS:
                    abstain_reason["AMBIGUOUS"] += 1
                    stat["tokens_abstained_ambiguous"] += 1
                else:
                    abstain_reason["safe_but_no_rule"] += 1
                if is_name:
                    stat["name_tokens_abstained"] += 1

        # ---- precision over rendered spans
        for m in matches:
            s, e = m.start, m.start + m.length
            span = sent[s:e]
            if not any(is_kanji(c) for c in span):
                continue
            stat["ruby_spans"] += 1
            if s in starts and e in ends:
                inner = [t for t in toks if t[0] >= s and t[1] <= e]
                gold = "".join(t[2] for t in inner)
                gold_l = "".join(t[3] or t[2] for t in inner)
            else:
                sub = subtoken_gold(sent, s, e, toks)
                if sub is None:
                    stat["unscorable"] += 1
                    continue
                gold = gold_l = sub
            if any(c.isdigit() or "\uFF10" <= c <= "\uFF19" for c in gold):
                # UniDic leaves digits unread ("6じ"), so a span containing one
                # cannot be scored against it either way.
                stat["unscorable"] += 1
                stat["unscorable_digits"] += 1
                continue
            got = kata_to_hira(match_reading(sent, m))
            if got == gold or got == gold_l:
                stat["correct"] += 1
            elif ORACLE_VARIANTS.get((span, gold)) == got:
                stat["oracle_variant"] += 1
            elif (m.rule.src and m.rule.src in verdicts
                  and len(verdicts[m.rule.src].entry_readings) > 1):
                # the oracle chose a different reading of the SAME entry, via
                # an inflected form: 目を開ける is めをあける or めをひらける
                stat["oracle_variant"] += 1
                stat["variant_same_entry"] += 1
            elif (m.rule.src and len(m.rule.src) > 1 and m.rule.src in verdicts
                  and verdicts[m.rule.src].safety is safety_mod.Safety.SAFE_UNIQUE
                  and sum(1 for t in toks if t[0] >= s and t[1] <= e) > 1):
                # 気に入る is one JMdict entry read きにいる; UniDic splits it
                # into 気 + に + 入っ and reads 入っ as はいっ.
                stat["oracle_variant"] += 1
                stat["oracle_token_concat"] += 1
            elif (span in verdicts and verdicts[span].reading == got
                  and sum(1 for t in toks if t[0] >= s and t[1] <= e) > 1):
                # The lexicon has this exact span as one entry (日曜日 ->
                # にちようび) but the tokenizer split it and concatenated
                # per-token readings, losing rendaku (にちよう + ひ).
                stat["oracle_variant"] += 1
                stat["oracle_token_concat"] += 1
            elif gold in (verdicts[span].entry_readings if span in verdicts else ()):
                # the oracle picked a different reading of the SAME lexeme
                # (明日 = あした / あす). Not a wrong reading.
                stat["oracle_variant"] += 1
                stat["variant_same_entry"] += 1
            else:
                stat["incorrect"] += 1
                rule = rule_by_seq.get(m.rule.seq)
                kind = _classify_error(span, got, gold, m, verdicts, rule)
                error_kinds[kind] += 1
                if len(errors) < 6000:
                    errors.append({
                        "span": span, "got": got, "gold": gold,
                        "rule": m.rule.seq, "origin": m.rule.origin,
                        "safety": m.rule.safety, "kind": kind,
                        "sentence": sent[:60],
                    })

    rendered = stat["correct"] + stat["incorrect"] + stat["oracle_variant"]
    # The question is "when YomiFont shows a reading, how often is it wrong?",
    # so the headline excludes disagreements that are demonstrably an oracle
    # convention rather than a YomiFont error.  Both numbers are reported.
    precision = (stat["correct"] + stat["oracle_variant"]) / max(1, rendered)
    precision_strict = stat["correct"] / max(1, rendered)
    coverage = stat["tokens_with_ruby"] / max(1, stat["eligible_tokens"])

    result = {
        "segmentation": args.segmentation,
        "rules": len(rs),
        "sentences": len(sentences),
        "eligible_tokens": stat["eligible_tokens"],
        "tokens_with_ruby": stat["tokens_with_ruby"],
        "tokens_abstained": stat["tokens_abstained"],
        "tokens_abstained_ambiguous": stat["tokens_abstained_ambiguous"],
        "ruby_spans": stat["ruby_spans"],
        "scored_spans": rendered,
        "correct": stat["correct"],
        "incorrect": stat["incorrect"],
        "oracle_variant": stat["oracle_variant"],
        "oracle_variant_same_entry": stat["variant_same_entry"],
        "oracle_variant_token_concat": stat["oracle_token_concat"],
        "unscorable_digits": stat["unscorable_digits"],
        "unscorable": stat["unscorable"],
        "precision": round(precision, 5),
        "precision_strict_oracle_variants_count_against": round(precision_strict, 5),
        "coverage": round(coverage, 5),
        "name_tokens": stat["name_tokens"],
        "name_tokens_with_ruby": stat["name_tokens_with_ruby"],
        "name_tokens_abstained": stat["name_tokens_abstained"],
        "abstain_reason": dict(abstain_reason),
        "error_kinds": dict(error_kinds.most_common()),
    }

    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    json.dump(result, open(args.report, "w"), ensure_ascii=False, indent=1)
    json.dump(errors, open(args.errors, "w"), ensure_ascii=False, indent=1)

    if args.quiet:
        print(f"precision={100*precision:.3f}% coverage={100*coverage:.2f}% "
              f"incorrect={stat['incorrect']} rules={len(rs)} seg={args.segmentation}")
        return 0

    print(f"[eval] {len(rs)} rules / {len(sentences)} sentences / "
          f"segmentation={args.segmentation}")
    print(f"\n  PRECISION  {100*precision:8.3f} %   "
          f"({rendered - stat['incorrect']} of {rendered} rendered readings OK)")
    print(f"    strict   {100*precision_strict:8.3f} %   "
          f"(oracle-convention differences counted as errors)")
    print(f"  INCORRECT  {stat['incorrect']:8d}")
    print(f"  coverage   {100*coverage:8.2f} %   "
          f"({stat['tokens_with_ruby']} of {stat['eligible_tokens']} kanji tokens)")
    print(f"\n  eligible tokens                 {stat['eligible_tokens']}")
    print(f"  tokens with ruby                {stat['tokens_with_ruby']}")
    print(f"  tokens abstained                {stat['tokens_abstained']}")
    print(f"     .. lexically ambiguous       {stat['tokens_abstained_ambiguous']}")
    for k, v in sorted(abstain_reason.items(), key=lambda kv: -kv[1]):
        print(f"     .. {k:26s} {v}")
    print(f"  ruby spans rendered             {stat['ruby_spans']}")
    print(f"     .. scored                    {rendered}")
    print(f"     .. unscorable vs tokenizer   {stat['unscorable']}")
    print(f"     .. oracle lemma convention   {stat['oracle_variant']}")
    print(f"  proper-name tokens              {stat['name_tokens']}")
    print(f"     .. with ruby                 {stat['name_tokens_with_ruby']}")
    print(f"     .. abstained                 {stat['name_tokens_abstained']}")
    print("\n  error classes:")
    for k, v in error_kinds.most_common():
        print(f"     {k:34s} {v}")
    print("\n  top incorrect:")
    seen: Counter = Counter()
    for e in errors:
        seen[(e["span"], e["got"], e["gold"], e["kind"])] += 1
    for (span, got, gold, kind), n in seen.most_common(args.show):
        print(f"     {n:5d}  {span:10s} got={got:12s} gold={gold:12s} {kind}")
    print(f"\n[eval] wrote {args.report} and {args.errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
