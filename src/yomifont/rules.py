"""Turn the lexical IR into the final rule set the font compiler consumes.

A rule is:

    seq      the exact surface characters that must be matched
    groups   ((start, length, reading), ...) positions relative to seq[0]
    pri      priority used for conflict resolution and for truncating the
             rule set when building smaller fonts

Everything here is deterministic; the only judgement calls are encoded as the
named constants at the top of the file so they can be measured and changed.
"""
from __future__ import annotations

import json
import math
import os
from collections import Counter, defaultdict
from dataclasses import dataclass

from .alignment import AlignError, RubyGroup, align
from .conjugation import IRREGULAR, SURU_NEXT, is_inflecting, stem_and_endings
from .jmdict import LexEntry
from .kana import is_kana as is_kana_str, is_kanji

# Expression entries that are just "common word + particle" must be DROPPED,
# not merely demoted.  Longest-match is decided by rule order inside a
# ChainSubRuleSet and therefore outranks priority: as long as a 今日は rule
# exists it beats 今日, and "今日は６月..." would get こんにちは.
PARTICLE_TAIL = set("はがをにでともへやかねよのだ")
EXPRESSION_POS = {"exp", "int", "adj-pn"}

# An entry is dropped only when it is *purely* a bound morpheme.  Testing for
# intersection instead of containment would throw away 山 (tagged ctr + n +
# n-pref) and leave only the noise reading むれ.
SKIP_POS = {"pref", "suf", "ctr", "aux", "aux-v", "aux-adj", "cop"}

# A rule whose surface is a single kanji is only safe when the entry is common;
# otherwise a rare single-kanji reading would fire on every occurrence of that
# character inside unknown compounds.
MIN_PRI_SINGLE_KANJI = 20

MAX_SEQ_LEN = 12
MAX_READING_LEN = 12

# Godan ending sets collide with the case particles: 雪ぐ (すすぐ, archaic)
# generates a 雪が rule that beats 雪 + が in "雪が降る".  Stem rules whose
# ending is one of these are only emitted for verbs the corpus actually
# attests, so a dead verb cannot shadow a live noun.
PARTICLE_ENDINGS = set("がにとのはもへ")

# Corpus evidence forms a TIER above JMdict's editorial priority rather than a
# bonus added to it.  A bounded bonus can never separate two readings that both
# max it out (行く/いく vs 行う/おこなう), and JMdict's own priority tags come
# from a newspaper corpus whose register differs from ordinary prose.
# A (surface, reading) pair attested in the corpus therefore outranks any
# unattested pair, and among attested pairs log-frequency decides.  JMdict
# priority survives only as a small tiebreak.
PRIOR_BASE = 10_000
PRIOR_SCALE = 200
PRIOR_TIEBREAK_CAP = 199  # < PRIOR_SCALE, so frequency always dominates

# ...but only once the evidence is worth trusting.  山道 is attested さんどう
# 10 times in the training corpus and やまみち zero times, yet JMdict ranks
# やまみち far higher (542 vs 271) and is right: UniDic's lemma reading for
# 山道 is サンドウ, so the corpus count is really a tokeniser convention, not
# usage.  Below the threshold the prior degrades to a bounded bonus that can
# nudge a ranking but not overturn one.
PRIOR_MIN_COUNT = 25
WEAK_PRIOR_SCALE = 40


OVERRIDE_PRIORITY = 1_000_000


def prior_priority(count: int) -> int:
    return PRIOR_BASE + int(PRIOR_SCALE * math.log1p(count))


def load_overrides(path: str) -> dict[str, str]:
    """surface -> chosen reading, from a reviewable TSV (see data/overrides.tsv)."""
    out: dict[str, str] = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0] and parts[1]:
                out[parts[0]] = parts[1]
    return out


@dataclass(slots=True)
class Rule:
    seq: str
    groups: tuple[tuple[int, int, str], ...]
    pri: int
    origin: str  # 'lex' | 'stem' | 'irregular'

    def key(self) -> str:
        return self.seq


def _is_word_plus_particle(entry: LexEntry, known: set[str]) -> bool:
    """True for entries like 今日は / 彼の that are a shorter word + a particle.

    Such entries are lexicalised phrases, but in running text the shorter word
    followed by a grammatical particle is far more common, and longest-match
    would otherwise always pick the phrase.
    """
    if not (set(entry.pos) & EXPRESSION_POS):
        return False
    s = entry.surface
    i = len(s)
    while i > 1 and s[i - 1] in PARTICLE_TAIL:
        i -= 1
    return i < len(s) and s[:i] in known


def _demote(entry: LexEntry) -> int:
    """Priority adjustment applied before conflict resolution."""
    pri = entry.pri
    if entry.flags:
        pri -= 10
    return pri


def _groups_tuple(groups: list[RubyGroup]) -> tuple[tuple[int, int, str], ...]:
    return tuple((g.start, g.length, g.reading) for g in groups)


def build_rules(
    entries: list[LexEntry],
    enable_inflection: bool = True,
    stats: dict | None = None,
    priors: dict[tuple[str, str], int] | None = None,
    overrides: dict[str, str] | None = None,
    abstain_margin: float = 0.0,
) -> list[Rule]:
    counts = Counter()
    fail_examples = defaultdict(list)
    candidates: dict[str, Rule] = {}
    runner_up: dict[str, int] = {}
    known_surfaces = {e.surface for e in entries}

    def offer(rule: Rule) -> None:
        prev = candidates.get(rule.seq)
        if prev is None:
            candidates[rule.seq] = rule
        elif rule.pri > prev.pri:
            if rule.groups != prev.groups:
                runner_up[rule.seq] = max(runner_up.get(rule.seq, 0), prev.pri)
            candidates[rule.seq] = rule
        elif rule.groups != prev.groups:
            runner_up[rule.seq] = max(runner_up.get(rule.seq, 0), rule.pri)
        counts["candidate_rules"] += 1

    for e in entries:
        counts["entries"] += 1
        bound_only = bool(e.pos) and set(e.pos) <= SKIP_POS
        if bound_only and len(e.surface) > 1:
            counts["skip_pos"] += 1
            continue
        if _is_word_plus_particle(e, known_surfaces):
            counts["skip_word_plus_particle"] += 1
            continue
        if len(e.surface) > MAX_SEQ_LEN or len(e.reading) > MAX_READING_LEN * 2:
            counts["skip_too_long"] += 1
            continue
        try:
            groups = align(e.surface, e.reading)
        except AlignError as err:
            counts["align_fail_" + err.kind] += 1
            if len(fail_examples[err.kind]) < 25:
                fail_examples[err.kind].append((e.surface, e.reading))
            continue
        if any(len(g.reading) > MAX_READING_LEN for g in groups):
            counts["skip_reading_too_long"] += 1
            continue
        counts["aligned"] += 1

        pri = _demote(e)
        if bound_only:
            # 達 -> たち is the only reading that exists, so the rule is useful;
            # but a bound morpheme must never outrank a free-standing word.
            pri -= 500
        if priors:
            n = priors.get((e.surface, e.reading))
            if n and n >= PRIOR_MIN_COUNT:
                pri = prior_priority(n) + min(pri, PRIOR_TIEBREAK_CAP)
                counts["prior_applied"] += 1
            elif n:
                pri += int(WEAK_PRIOR_SCALE * math.log1p(n))
                counts["weak_prior_applied"] += 1
        if overrides:
            want = overrides.get(e.surface)
            if want is not None:
                if want == e.reading:
                    pri = OVERRIDE_PRIORITY
                    counts["override_applied"] += 1
                else:
                    pri = -OVERRIDE_PRIORITY
        if len(e.surface) == 1 and is_kanji(e.surface) and pri < MIN_PRI_SINGLE_KANJI:
            counts["skip_rare_single_kanji"] += 1
        else:
            offer(Rule(e.surface, _groups_tuple(groups), pri, "lex"))

        if not enable_inflection:
            continue

        # suru-nouns: 勉強 -> 勉強し / 勉強す / 勉強さ / 勉強せ
        if "vs" in e.pos and e.surface and not is_kana_str(e.surface[-1]):
            g = _groups_tuple(groups)
            for ch in SURU_NEXT:
                offer(Rule(e.surface + ch, g, pri, "suru"))
            counts["suru_rules"] += len(SURU_NEXT)

        # irregular paradigms first (来る etc.)
        if e.surface and e.surface[0] in IRREGULAR and is_inflecting(e.pos):
            for form, reading in IRREGULAR[e.surface[0]]:
                if not form.startswith(e.surface[0]):
                    continue
                offer(Rule(form, ((0, 1, reading),), pri + 5, "irregular"))
            counts["irregular"] += 1
            continue

        if not is_inflecting(e.pos):
            continue
        se = stem_and_endings(e.surface, e.pos)
        if se is None:
            counts["stem_none"] += 1
            continue
        stem, nexts = se
        # every ruby group must live inside the stem, otherwise the rule would
        # claim to know the reading of a character it does not match
        if any(g.start + g.length > len(stem) for g in groups):
            counts["stem_group_overflow"] += 1
            continue
        stem_groups = _groups_tuple([g for g in groups if g.start < len(stem)])
        if not stem_groups:
            counts["stem_no_groups"] += 1
            continue
        attested = bool(priors and priors.get((e.surface, e.reading)))
        if not nexts:
            offer(Rule(stem, stem_groups, pri, "stem"))
            counts["stem_rules"] += 1
        else:
            for ch in nexts:
                if ch in PARTICLE_ENDINGS and not attested:
                    counts["stem_particle_skipped"] += 1
                    continue
                offer(Rule(stem + ch, stem_groups, pri, "stem"))
                counts["stem_rules"] += 1

    rules = list(candidates.values())

    # Abstention.  Some surfaces are genuinely undecidable without sentence
    # context (人気 にんき/ひとけ, 市場 しじょう/いちば): the font layer cannot
    # see what would settle them, and a confident wrong reading is worse for a
    # reader than none.  When abstain_margin is set, a rule is dropped if its
    # runner-up reading is within that ratio of the winner on the same scale.
    if abstain_margin:
        kept = []
        for r in rules:
            second = runner_up.get(r.seq, 0)
            if second > 0 and r.pri > 0 and second >= r.pri / abstain_margin:
                counts["abstained"] += 1
                if len(fail_examples["abstained"]) < 40:
                    fail_examples["abstained"].append((r.seq, r.groups[0][2] if r.groups else ""))
                continue
            kept.append(r)
        rules = kept

    rules.sort(key=lambda r: (-len(r.seq), -r.pri, r.seq))
    counts["final_rules"] = len(rules)

    if stats is not None:
        stats["counts"] = dict(counts)
        stats["align_failures"] = {k: v for k, v in fail_examples.items()}
    return rules


# A lone-kanji fallback is adopted only with this much corpus support.
LONE_KANJI_MIN_COUNT = 8

# Counts arrive as [whole, stem]:
#   whole  the kanji IS the whole token (noun 話 / はなし)
#   stem   a lone Han run inside a longer token (話し / はなし)
# Every engine reaches the single-character rule in the `whole` case, but only
# Blink reaches it in the `stem` case -- elsewhere a longer stem rule matches
# first.  Weighting `whole` twice therefore minimises total errors across both
# engine families.  Without the weighting the stem reading wins narrow races
# and 話 becomes はな, 上 becomes あ, 時 becomes と.
WHOLE_TOKEN_WEIGHT = 2


def add_lone_kanji_fallbacks(
    rules: list[Rule],
    lone_counts: dict[tuple[str, str], int],
    stats: dict | None = None,
) -> list[Rule]:
    """Set the single-character rule for each kanji to its lone-run reading.

    Motivation is compatibility, not linguistics.  Blink itemises text into
    script runs before shaping, so in Chrome a kanji surrounded by okurigana is
    shaped entirely alone: 行った is shaped as 行 + った and only the
    single-character 行 rule can ever fire.  Picking that rule's reading from
    JMdict's noun entry gives ぎょう; picking it from how 行 is actually read
    when it stands alone between kana gives い, which is right 3868 times to
    25 in the training corpus.

    The reading is never invented -- it must already be one YomiFont assigns to
    that character in some other rule.  Engines that do not segment (HarfBuzz,
    CoreText) are barely affected, because a longer rule matches first there.
    """
    counts = Counter()
    assigned: dict[str, set[str]] = defaultdict(set)
    for r in rules:
        for start, length, reading in r.groups:
            if length == 1:
                assigned[r.seq[start]].add(reading)

    best: dict[str, tuple[int, str]] = {}
    for (kanji, reading), counts_pair in lone_counts.items():
        if isinstance(counts_pair, int):
            whole, stem = 0, counts_pair
        else:
            whole, stem = counts_pair
        score = WHOLE_TOKEN_WEIGHT * whole + stem
        if score < LONE_KANJI_MIN_COUNT or reading not in assigned.get(kanji, ()):
            continue
        cur = best.get(kanji)
        if cur is None or score > cur[0] or (score == cur[0] and reading < cur[1]):
            best[kanji] = (score, reading)

    by_seq = {r.seq: r for r in rules}
    out = list(rules)
    for kanji, (n, reading) in sorted(best.items()):
        groups = ((0, 1, reading),)
        prev = by_seq.get(kanji)
        if prev is not None and prev.pri >= OVERRIDE_PRIORITY:
            counts["lone_kanji_kept_override"] += 1
            continue
        if prev is None:
            out.append(Rule(kanji, groups, prior_priority(n), "lone"))
            counts["lone_kanji_added"] += 1
        elif prev.groups != groups:
            prev.groups = groups
            prev.pri = prior_priority(n)
            prev.origin = "lone"
            counts["lone_kanji_replaced"] += 1
        else:
            counts["lone_kanji_unchanged"] += 1

    if stats is not None:
        stats.setdefault("counts", {}).update(counts)
    out.sort(key=lambda r: (-len(r.seq), -r.pri, r.seq))
    return out


def ambiguity_report(entries: list[LexEntry]) -> dict:
    """How much of the lexicon is genuinely ambiguous at the surface level?"""
    by_surface: dict[str, list[LexEntry]] = defaultdict(list)
    for e in entries:
        by_surface[e.surface].append(e)
    total = len(by_surface)
    multi = {s: v for s, v in by_surface.items() if len({x.reading for x in v}) > 1}
    # a conflict is "decidable" when one candidate is strictly more common
    decidable = 0
    tied = []
    for s, v in multi.items():
        best = max(_demote(x) for x in v)
        winners = {x.reading for x in v if _demote(x) == best}
        if len(winners) == 1:
            decidable += 1
        else:
            tied.append((s, sorted(winners)))
    return {
        "distinct_surfaces": total,
        "single_reading": total - len(multi),
        "multi_reading": len(multi),
        "multi_reading_decidable_by_priority": decidable,
        "multi_reading_tied": len(tied),
        "tied_examples": tied[:40],
    }


def save(rules: list[Rule], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rules:
            fh.write(
                json.dumps([r.seq, [list(g) for g in r.groups], r.pri, r.origin],
                           ensure_ascii=False, separators=(",", ":")) + "\n"
            )


def load(path: str) -> list[Rule]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            seq, groups, pri, origin = json.loads(line)
            out.append(Rule(seq, tuple(tuple(g) for g in groups), pri, origin))
    return out
