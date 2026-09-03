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

# Person names are excluded in BOTH directions -- neither used as a reading
# source nor allowed to veto one.  A surname reading of 学 does not make the
# ordinary noun 学 ambiguous in running text, and admitting them as competitors
# would silently delete large numbers of perfectly safe common words.
EXCLUDED_NAME_TYPES = PERSON_LIKE


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
            return False
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
