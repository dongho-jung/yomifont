"""Turn the classified lexicon into the rule set the font compiler consumes.

Phase 2 policy: **a rule exists only when its reading is determined.**  Where
Phase 1 resolved a conflict by picking the most frequent candidate, this
version drops the rule.  Corpus frequency is not consulted at all when deciding
what a word reads -- it can tell you which reading is more common, never that
the other one is wrong.

A rule is:

    seq      the exact surface characters that must be matched
    groups   ((start, length, reading), ...) offsets relative to seq[0]
    safety   why this rule is considered safe
    origin   which generator produced it
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass

from .alignment import AlignError, RubyGroup, align
from .conjugation import IRREGULAR, SURU_NEXT, is_inflecting, stem_and_endings
from .kana import is_kana, is_kanji
from .lexicon import LexEntry
from .safety import Safety, SurfaceVerdict, admissible

# Entries that are only ever bound morphemes never become rules of their own:
# 達 as a standalone word is not something running text contains.
BOUND_POS = {"pref", "suf", "ctr", "aux", "aux-v", "aux-adj", "cop"}

# Expression entries that are a shorter word plus a particle (今日は, 彼の).
# Longest match is rule order, so these always beat the shorter word and have
# to be removed rather than down-ranked.
PARTICLE_TAIL = set("はがをにでともへやかねよのだ")
EXPRESSION_POS = {"exp", "int", "adj-pn"}

# Godan ending sets collide with the case particles: 雪ぐ (すすぐ) would
# generate a 雪が rule that beats 雪 + が in "雪が降る".  When the stem is
# itself a known word, that sequence is ambiguous and gets no rule.
PARTICLE_ENDINGS = set("がにとのはもへ")

MAX_SEQ_LEN = 12
MAX_READING_LEN = 12

# A single kanji has a determinable reading only when it stands alone, and the
# font cannot tell that: inside an unknown compound the same rule fires and
# prints the free-standing reading (蓮花 -> はす+はな, not れんげ).  Expressing
# "only when not adjacent to another kanji" needs both a backtrack and a
# lookahead guard, which then fails at the start of every shaping run -- and in
# Blink every lone kanji IS at the start of its run.  Measured on the held-out
# corpus, dropping them costs 4.4 points of coverage and removes 26 of 59
# remaining wrong readings, which is the trade this project is set up to take.
MIN_SEQ_LEN = 2


@dataclass(slots=True)
class Rule:
    seq: str
    groups: tuple[tuple[int, int, str], ...]
    safety: str
    origin: str  # 'lex' | 'name' | 'stem' | 'suru' | 'irregular' | 'block'
    src: str = ""  # the lexicon surface this rule was derived from

    def as_row(self) -> list:
        return [self.seq, [list(g) for g in self.groups], self.safety, self.origin,
                self.src]

    @staticmethod
    def from_row(r: list) -> "Rule":
        return Rule(r[0], tuple(tuple(g) for g in r[1]), r[2], r[3],
                    r[4] if len(r) > 4 else "")


def _groups_tuple(groups: list[RubyGroup]) -> tuple[tuple[int, int, str], ...]:
    return tuple((g.start, g.length, g.reading) for g in groups)


def _is_word_plus_particle(surface: str, pos: tuple[str, ...], known: set[str]) -> bool:
    if not (set(pos) & EXPRESSION_POS):
        return False
    i = len(surface)
    while i > 1 and surface[i - 1] in PARTICLE_TAIL:
        i -= 1
    return i < len(surface) and surface[:i] in known


def build_rules(
    entries: list[LexEntry],
    verdicts: dict[str, SurfaceVerdict],
    stats: dict | None = None,
) -> list[Rule]:
    counts: Counter = Counter()
    examples: dict[str, list] = defaultdict(list)

    # Winning entry per safe surface, so POS (needed for conjugation) comes
    # from the entry whose reading we actually adopted.
    winner: dict[str, LexEntry] = {}
    all_surfaces: set[str] = set()
    in_jmdict = {e.surface for e in entries if e.source == "jmdict" and e.live}
    # POS of the competing entries behind an ambiguous surface, so its
    # inflected forms can be blocked too.
    ambiguous_pos: dict[str, set[str]] = defaultdict(set)
    for e in entries:
        if not admissible(e, name_only=e.surface not in in_jmdict):
            continue
        all_surfaces.add(e.surface)
        v0 = verdicts.get(e.surface)
        if v0 is not None and v0.safety is Safety.AMBIGUOUS:
            ambiguous_pos[e.surface].update(e.pos)
        v = verdicts.get(e.surface)
        if v is None or v.safety is not Safety.SAFE_UNIQUE or v.reading != e.reading:  # noqa: E501
            continue
        cur = winner.get(e.surface)
        if cur is None or (e.source == "jmdict" and cur.source != "jmdict") \
           or (e.source == cur.source and e.rank < cur.rank):
            winner[e.surface] = e

    # seq -> {tier -> {layout -> origin}}.  A direct lexical entry for exactly
    # this surface is stronger evidence than a form derived from some longer
    # verb, so the tiers are resolved in order rather than pooled: 同じ is the
    # adjective おなじ, not the 連用形 of the rare 同じる (どうじる).
    LEX, DERIVED = 0, 1
    proposals: dict[str, list[dict[tuple, str]]] = defaultdict(lambda: [{}, {}])

    def offer(seq: str, groups: tuple, origin: str, src: str) -> None:
        tier = LEX if origin in ("lex", "name") else DERIVED
        proposals[seq][tier][groups] = (origin, src)

    for surface, e in winner.items():
        counts["safe_surfaces"] += 1
        if e.pos and set(e.pos) <= BOUND_POS:
            counts["skip_bound_morpheme"] += 1
            continue
        if _is_word_plus_particle(surface, e.pos, all_surfaces):
            counts["skip_word_plus_particle"] += 1
            continue
        if len(surface) > MAX_SEQ_LEN or len(e.reading) > MAX_READING_LEN * 2:
            counts["skip_too_long"] += 1
            continue
        try:
            groups = align(surface, e.reading)
        except AlignError as err:
            counts["UNSAFE_ALIGNMENT"] += 1
            if len(examples["alignment"]) < 25:
                examples["alignment"].append((surface, e.reading, err.kind))
            continue
        if any(len(g.reading) > MAX_READING_LEN for g in groups):
            counts["skip_reading_too_long"] += 1
            continue

        gt = _groups_tuple(groups)
        if len(surface) < MIN_SEQ_LEN:
            counts["skip_single_kanji"] += 1
            continue
        if e.source == "jmnedict":
            # A one-character "name" is a zodiac sign or an initial, never
            # something running text means: 子 -> ね, 国 -> こく.
            if len(surface) < 2:
                counts["skip_single_char_name"] += 1
                continue
            offer(surface, gt, "name", surface)
            counts["name_rules"] += 1
        else:
            offer(surface, gt, "lex", surface)
            counts["lex_rules"] += 1

        # ---- inflection ---------------------------------------------------
        if "vs" in e.pos and surface and not is_kana(surface[-1]):
            for ch in SURU_NEXT:
                offer(surface + ch, gt, "suru", surface)
            counts["suru_rules"] += len(SURU_NEXT)

        if surface and surface[0] in IRREGULAR and is_inflecting(e.pos):
            for form, reading in IRREGULAR[surface[0]]:
                offer(form, ((0, 1, reading),), "irregular", surface)
            counts["irregular_rules"] += 1
            continue

        if not is_inflecting(e.pos):
            continue
        se = stem_and_endings(surface, e.pos)
        if se is None:
            continue
        stem, nexts = se
        if any(g.start + g.length > len(stem) for g in groups):
            counts["skip_stem_group_overflow"] += 1
            continue
        stem_groups = _groups_tuple([g for g in groups if g.start < len(stem)])
        if not stem_groups:
            continue
        if not nexts and len(stem) >= MIN_SEQ_LEN:
            offer(stem, stem_groups, "stem", surface)
            counts["stem_rules"] += 1
        else:
            for ch in nexts:
                if ch in PARTICLE_ENDINGS and (stem in all_surfaces):
                    # 雪 + が could be the noun with a particle
                    counts["skip_stem_particle_collision"] += 1
                    continue
                if len(stem + ch) < MIN_SEQ_LEN:
                    continue
                offer(stem + ch, stem_groups, "stem", surface)
                counts["stem_rules"] += 1

    # ---- resolve ----------------------------------------------------------
    ambiguous_surfaces = {s for s, v in verdicts.items() if v.safety is Safety.AMBIGUOUS}

    # An ambiguous word's INFLECTED forms are ambiguous too, and blocking only
    # the dictionary form leaves the single-kanji rule free to fire on them:
    # 強い is blocked but 強く was not, so 強 printed きょう.  Same for
    # 注ぐ/注い, 打つ/打っ, 回る/回っ.
    for surf, pos in ambiguous_pos.items():
        se = stem_and_endings(surf, tuple(sorted(pos)))
        if se is None:
            continue
        stem, nexts = se
        for ch in (nexts or ""):
            ambiguous_surfaces.add(stem + ch)
        if not nexts:
            ambiguous_surfaces.add(stem)
    # A word plus a particle inherits the word's ambiguity: 時 is ambiguous, so
    # the lexicalised 時に cannot be resolved either -- in "3時に" it is じに.
    # But only when the sequence is a bare lexical entry.  書 is ambiguous too,
    # and 書か would be caught by the same test, yet there it is the 未然形 of
    # 書く and the okurigana determines it completely.  A derived proposal is
    # exactly that evidence, so its presence exempts the sequence.
    for surf in list(ambiguous_surfaces):
        for ch in PARTICLE_TAIL:
            ext = surf + ch
            tiers = proposals.get(ext)
            if tiers is not None and tiers[DERIVED]:
                continue
            if ext in all_surfaces or tiers is not None:
                ambiguous_surfaces.add(ext)
    rules: list[Rule] = []
    blocked: set[str] = set()
    for seq in set(proposals) | ambiguous_surfaces:
        if seq in ambiguous_surfaces:
            # The sequence itself is a word with more than one reading. No rule
            # may claim it -- not even one derived from a different verb, which
            # is how 強い (こわい/つよい) was getting し from 強いる.
            counts["blocked_ambiguous_surface"] += 1
            blocked.add(seq)
            continue
        tiers = proposals.get(seq)
        if tiers is None:
            continue
        # A lexical entry and a derived form claiming the same sequence with
        # different readings is a real ambiguity, not a ranking problem:
        # 説明し is 説明+し (せつめいし) or the noun 説明し (ときあかし), and
        # nothing structural separates them. Precision-first says neither.
        if tiers[LEX] and tiers[DERIVED] and set(tiers[LEX]) != set(tiers[DERIVED]):
            counts["blocked_lex_vs_derived"] += 1
            blocked.add(seq)
            continue
        layouts = tiers[LEX] or tiers[DERIVED]
        if len(layouts) > 1:
            counts["blocked_conflicting_derivations"] += 1
            if len(examples["conflicting"]) < 40:
                examples["conflicting"].append(
                    (seq, sorted({"".join(g[2] for g in gs) for gs in layouts}))
                )
            blocked.add(seq)
            continue
        groups, (origin, src) = next(iter(layouts.items()))
        safety = Safety.SAFE_UNIQUE.value if origin in ("lex", "name") \
            else Safety.SAFE_CONTEXTUAL.value
        rules.append(Rule(seq, groups, safety, origin, src))

    # ---- okurigana-less spelling variants ---------------------------------
    # JMdict lists 気持 and 気持ち under ONE entry, both read きもち: the first
    # is just the okurigana-less spelling. Aligning it puts the whole reading
    # on two characters, so in Chrome -- where the Han run 気持 is shaped alone
    # -- 気持ちがいい gets きもち over 気持 and a bare ち after it. Keeping only
    # the spelled-out form removes the whole class (金持, 支払, 年寄, 見舞,
    # 手洗, 目指, 腰掛 ...).
    surfaces_of_entry: dict[int, list[str]] = defaultdict(list)
    for surf, e in winner.items():
        surfaces_of_entry[e.seq].append(surf)
    okurigana_less: set[str] = set()
    for surfs in surfaces_of_entry.values():
        if len(surfs) < 2:
            continue
        for surf in surfs:
            if not all(is_kanji(c) for c in surf):
                continue
            for longer in surfs:
                if (len(longer) > len(surf) and longer.startswith(surf)
                        and all(is_kana(c) for c in longer[len(surf):])):
                    okurigana_less.add(surf)
                    break
    if okurigana_less:
        counts["dropped_okurigana_less_variant"] = len(okurigana_less)
        rules = [r for r in rules if r.seq not in okurigana_less]

    # ---- script-segmentation safety --------------------------------------
    # Blink shapes each Han run separately, so an all-Han rule that is also the
    # stem of a DIFFERENT, inflecting word fires on that word too -- and there
    # the reading is different. 微笑 is the noun びしょう and also the stem of
    # 微笑む (ほほえ); in Chrome the Han run is just 微笑 and nothing downstream
    # can tell them apart, so the prefix rule is not determined.
    #
    # Restricted to hiragana tails and to *inflected* longer forms on purpose:
    # a katakana tail is a compound name (日本ハム reads にっぽん, which would
    # otherwise delete 日本), and a longer plain lexical entry is a separate
    # fixed word (今日た / こんにった must not delete 今日).
    by_seq = {r.seq: r for r in rules}

    def _prefix_ruby(r, n):
        return tuple(g for g in r.groups if g[0] + g[1] <= n)

    unsafe_prefix: set[str] = set()
    for r in rules:
        if r.origin not in ("stem", "suru", "irregular"):
            continue
        seq = r.seq
        for i in range(2, len(seq)):
            head, tail = seq[:i], seq[i:]
            if not all(is_kanji(c) for c in head):
                continue
            if not all(0x3041 <= ord(c) <= 0x309F for c in tail):
                continue
            other = by_seq.get(head)
            if other is None or other.origin == "block":
                continue
            if _prefix_ruby(other, i) != _prefix_ruby(r, i):
                unsafe_prefix.add(head)
    if unsafe_prefix:
        counts["dropped_unsafe_under_segmentation"] = len(unsafe_prefix)
        rules = [r for r in rules if r.seq not in unsafe_prefix]

    # ---- blocking rules ---------------------------------------------------
    # Abstaining is only real if nothing shorter fires in the abstained
    # sequence's place. 難しい is ambiguous, but without a rule covering it the
    # single-character 難 rule matches and prints なん. A rule with no ruby
    # consumes the sequence and produces nothing, which is what abstention
    # has to mean at the shaping layer.
    have = {r.seq for r in rules}
    for seq in sorted(blocked):
        if len(seq) < 2:
            continue
        if any(seq[:i] in have for i in range(1, len(seq))):
            rules.append(Rule(seq, (), Safety.AMBIGUOUS.value, "block", seq))
            counts["block_rules"] += 1

    rules.sort(key=lambda r: (-len(r.seq), r.seq))
    counts["final_rules"] = len(rules)
    counts["final_safe_unique"] = sum(1 for r in rules if r.safety == Safety.SAFE_UNIQUE.value)
    counts["final_safe_contextual"] = sum(
        1 for r in rules if r.safety == Safety.SAFE_CONTEXTUAL.value)
    counts["final_name_rules"] = sum(1 for r in rules if r.origin == "name")
    counts["final_block_rules"] = sum(1 for r in rules if r.origin == "block")
    if stats is not None:
        stats["counts"] = dict(counts)
        stats["examples"] = {k: v for k, v in examples.items()}
    return rules


def save(rules: list[Rule], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rules:
            fh.write(json.dumps(r.as_row(), ensure_ascii=False, separators=(",", ":")) + "\n")


def load(path: str) -> list[Rule]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            out.append(Rule.from_row(json.loads(line)))
    return out
