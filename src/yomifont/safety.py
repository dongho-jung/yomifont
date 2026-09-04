"""Safe-reading classifier.

The product rule is: **never show a reading that might be wrong**.  So a
surface earns ruby only when the lexical data says its reading is determined,
and the classifier's job is to make that judgement structurally rather than
probabilistically.

The load-bearing signal is *entry identity*:

    今日   きょう / こんにち     one JMdict entry   -> variant readings, safe
    市場   しじょう / いちば     two JMdict entries -> two words, abstain
    行く   いく / ゆく           one entry          -> safe
    人気   にんき / ひとけ       two entries        -> abstain

Two readings inside one entry are alternative pronunciations of one lexeme;
picking the prominent one is not an error.  Two readings in two entries are
two different words that happen to share a spelling, and nothing visible to a
shaping engine can tell them apart.

Frequency is deliberately NOT used to break these ties.  A corpus can tell you
which reading is more common; it cannot tell you that the other one is wrong.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from .jmnedict import PERSON_LIKE, PLACE_LIKE
from .lexicon import LexEntry


class Safety(str, Enum):
    SAFE_UNIQUE = "SAFE_UNIQUE"
    SAFE_CONTEXTUAL = "SAFE_CONTEXTUAL"
    AMBIGUOUS = "AMBIGUOUS"
    UNSAFE_ALIGNMENT = "UNSAFE_ALIGNMENT"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    UNSUPPORTED_SHAPER_CONTEXT = "UNSUPPORTED_SHAPER_CONTEXT"


# JMnedict name types admitted to the lexicon, chosen from the measured
# multi-reading rate of each type (see jmnedict.ambiguity_by_type):
#
#     station       0.11 %      organization  0.96 %
#     person        1.97 %      work          3.86 %
#     company       5.97 %      place        11.20 %
#     fem          21.65 %      masc         27.59 %
#     unclass      29.51 %      surname      33.06 %      given  36.72 %
#
# A type where a third of all spellings are already known to be multi-read
# cannot be trusted when a particular entry happens to list only one reading:
# that is far more likely to be incomplete data than evidence of uniqueness.
NAME_TYPE_MAX_AMBIGUITY = 0.12

# Person names are never used as a *reading source* for a surface that also
# exists in JMdict: a type where a third of all spellings are multi-read cannot
# be trusted to have listed the only reading.
EXCLUDED_NAME_TYPES = PERSON_LIKE

# ...but they ARE allowed to veto one.
#
# This was the other way round on the argument that a surname reading of 学
# does not make the ordinary noun 学 ambiguous.  Measured, that argument costs
# precision: 12 of the 31 wrong readings left in a 20,000-sentence evaluation
# are exactly this -- 上野 read こうずけ where the text meant うえの, 平野
# へいや for ひらの, 陽子 ようし for ようこ.  The font cannot tell which sense
# is meant, which is the definition of ambiguous.
#
# The trade is measured, not assumed: vetoing costs 7,734 of 197,831 surfaces
# (3.9 %) and 6.3 % of ruby spans in running text.  Precision is the primary
# objective and coverage is secondary, so it is worth taking -- but it is a big
# enough lever to stay switchable.
PERSON_NAMES_VETO = True

# Proper nouns whose several listed readings collapse to one in running text.
# See the note at the use site: this is the only place corpus evidence selects
# a reading rather than only removing one, and it is fenced to JMnedict-only
# surfaces. `NAME_CORPUS` is loaded by the pipeline from build_polyphony.py.
NAME_CORPUS_DISAMBIGUATION = True
NAME_CORPUS_MIN_HITS = 2
NAME_CORPUS: dict[str, dict[str, int]] = {}


@dataclass(slots=True)
class SurfaceVerdict:
    surface: str
    safety: Safety
    reading: str | None
    entries: int
    readings: tuple[str, ...]      # one per competing entry
    sources: tuple[str, ...]
    ntypes: tuple[str, ...]
    # every reading listed inside the winning entry.  These are alternative
    # pronunciations of one lexeme (明日 = あした / あす / みょうにち), so a
    # disagreement with an oracle that picked a different one is not an error.
    entry_readings: tuple[str, ...] = ()


def admissible(e: LexEntry, name_only: bool = False) -> bool:
    """Can this entry take part in the reading decision at all?

    `name_only` means the surface exists nowhere in JMdict.  Person-name types
    are suppressed for ordinary vocabulary -- a surname reading of 学 does not
    make the noun 学 ambiguous in running text -- but for a surface that is
    *only* ever a name they are exactly the competitors that matter: without
    them 田中 loses its surname reading たなか and takes the Chinese place
    reading てぃえんじょん instead.
    """
    if not e.live:
        return False
    if e.source == "jmnedict":
        if not e.ntype:
            return False
        if name_only:
            return True
        if set(e.ntype) & EXCLUDED_NAME_TYPES:
            # Admitted only as a competitor, never as the reading that gets
            # rendered: `classify` sees more than one reading for the surface
            # and abstains. See PERSON_NAMES_VETO.
            return PERSON_NAMES_VETO
        return bool(set(e.ntype) & PLACE_LIKE)
    return True


def classify(entries: list[LexEntry]) -> dict[str, SurfaceVerdict]:
    """One verdict per surface form."""
    in_jmdict = {e.surface for e in entries if e.source == "jmdict" and e.live}
    by_surface: dict[str, list[LexEntry]] = defaultdict(list)
    for e in entries:
        if admissible(e, name_only=e.surface not in in_jmdict):
            by_surface[e.surface].append(e)

    out: dict[str, SurfaceVerdict] = {}
    for surface, es in by_surface.items():
        # JMnedict EXTENDS the lexicon; it never vetoes it.  Its own DTD calls
        # it "a quick-and-dirty conversion of the ENAMDICT entries", and its
        # coverage of obscure toponyms means almost any common word collides
        # with some hamlet: 下宿 (げしゅく) with したじゅく, 東京 with とうけい.
        # Admitting those as competitors would delete 450 EDRDG-common words,
        # all of that shape.  So when the general dictionary has an opinion,
        # only the general dictionary votes.
        jm = [e for e in es if e.source == "jmdict"]
        if jm:
            # ...with one exception. The argument above is about *toponyms*:
            # JMnedict knows a hamlet for nearly every common word and those
            # collisions are noise. Person names are a different case, because
            # a personal name is what the text actually means often enough to
            # matter -- 上野, 平野, 陽子, 高木 are ordinary words *and* the
            # names of people being talked about. Measured over 20,000
            # sentences, 12 of the 31 remaining wrong readings are precisely
            # this. They vote; see PERSON_NAMES_VETO.
            # ...and only against a word EDRDG has *not* marked common. That
            # qualifier is load-bearing. Without it an obscure surname deletes
            # a very common word: JMnedict lists 日本 as やまと and 京都 as
            # みやこ, and vetoing on those removes 日本 and 京都 outright. The
            # surfaces this is meant to catch -- 上野 こうずけ, 平野 へいや,
            # 陽子 ようし -- are the reverse case, an unmarked dictionary word
            # colliding with a name people actually use. EDRDG's priority flag
            # is editorial evidence about the *word*; it is used here only to
            # decide whether a competing name reading is real, never to pick
            # between readings.
            if PERSON_NAMES_VETO and not any(e.pri for e in jm):
                jm += [e for e in es if e.source == "jmnedict"
                       and set(e.ntype) & PERSON_LIKE]
            es = jm

        # the reading each ENTRY prefers: its lowest-rank reading
        preferred: dict[int, LexEntry] = {}
        for e in es:
            cur = preferred.get(e.seq)
            if cur is None or e.rank < cur.rank:
                preferred[e.seq] = e
        readings = {e.reading for e in preferred.values()}
        sources = tuple(sorted({e.source for e in es}))
        ntypes = tuple(sorted({t for e in es for t in e.ntype}))

        # A proper noun with several listed readings where running text only
        # ever uses one of them.  JMnedict has five entries for 新宿 --
        # あらじゅく, しんしく, しんしゅく, しんじゅく, にいじゅく -- all typed
        # `place`, all priority 0, so nothing in the lexical data ranks them;
        # four are hamlets nobody writes about.  Treating that as undetermined
        # loses 新宿, and 新宿 is しんじゅく.
        #
        # This is the one place corpus evidence *selects* rather than only
        # removes, and it is deliberately fenced: proper nouns only, only when
        # the corpus attests exactly one of the listed readings, and the
        # reading still has to come from the lexicon. A word JMdict knows never
        # reaches here.
        if (len(readings) > 1 and NAME_CORPUS_DISAMBIGUATION
                and sources == ("jmnedict",)):
            hits = {r: NAME_CORPUS.get(surface, {}).get(r, 0) for r in readings}
            live = [r for r, n in hits.items() if n >= NAME_CORPUS_MIN_HITS]
            if len(live) == 1:
                winner = min((e for e in preferred.values() if e.reading == live[0]),
                             key=lambda e: (e.rank, -e.pri, e.seq))
                out[surface] = SurfaceVerdict(
                    surface, Safety.SAFE_UNIQUE, winner.reading, len(preferred),
                    tuple(sorted(readings)), sources, ntypes, (winner.reading,))
                continue

        if len(readings) == 1:
            winner = min(preferred.values(), key=lambda e: (e.rank, -e.pri, e.seq))
            same_entry = tuple(sorted({e.reading for e in es if e.seq == winner.seq}))
            out[surface] = SurfaceVerdict(surface, Safety.SAFE_UNIQUE, winner.reading,
                                          len(preferred), tuple(sorted(readings)),
                                          sources, ntypes, same_entry)
        else:
            out[surface] = SurfaceVerdict(surface, Safety.AMBIGUOUS, None,
                                          len(preferred), tuple(sorted(readings)),
                                          sources, ntypes)
    return out


def entry_reading_is_safe(e: LexEntry, verdicts: dict[str, SurfaceVerdict]) -> bool:
    v = verdicts.get(e.surface)
    return v is not None and v.safety is Safety.SAFE_UNIQUE and v.reading == e.reading


def report(verdicts: dict[str, SurfaceVerdict], entries: list[LexEntry]) -> dict:
    total = len(verdicts)
    safe = sum(1 for v in verdicts.values() if v.safety is Safety.SAFE_UNIQUE)
    amb = total - safe
    by_source: dict[str, dict[str, int]] = defaultdict(lambda: {"safe": 0, "ambiguous": 0})
    for v in verdicts.values():
        key = "+".join(v.sources)
        by_source[key]["safe" if v.safety is Safety.SAFE_UNIQUE else "ambiguous"] += 1
    dropped_names = len({e.surface for e in entries
                         if e.source == "jmnedict" and not admissible(e)}
                        - set(verdicts))
    return {
        "surfaces_considered": total,
        "safe_unique": safe,
        "ambiguous": amb,
        "safe_pct": round(100 * safe / max(1, total), 2),
        "by_source": {k: dict(v) for k, v in sorted(by_source.items())},
        "name_surfaces_excluded_by_type": dropped_names,
    }
