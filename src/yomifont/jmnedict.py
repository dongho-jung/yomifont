"""JMnedict -> the same lexical IR as JMdict.

JMnedict is the EDRDG named-entity dictionary: ~740k entries covering
surnames, given names, place names, stations, companies, products and works.
It is licensed under the same EDRDG Creative Commons Attribution-ShareAlike
terms as JMdict (see docs/licensing.md).

Proper nouns are NOT excluded on principle here.  The question is only whether
a spelling has one safe reading:

    東京    place        one reading   とうきょう      -> usable
    任天堂  company      one reading   にんてんどう    -> usable
    山崎    surname      やまざき / やまさき / ...      -> not usable

Person-name types are the dangerous ones: the same characters are read
differently by different people, and JMnedict listing only one reading is
often incomplete data rather than evidence of uniqueness.  `ambiguity_by_type`
measures that per name type from the data itself so the inclusion policy can
be set on evidence instead of intuition.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .jmdict import _open, entity_map, iter_entries  # noqa: F401
from .kana import is_kana, is_kanji, normalize_reading, strip_non_reading
from .lexicon import LexEntry

# JMnedict name_type codes, grouped by how safe a single listed reading is.
#
# Toponyms and institutions are named once, officially, and JMnedict's coverage
# of them is good; a place with two readings is genuinely two places.
PLACE_LIKE = {"place", "station", "company", "organization", "product", "work",
              "dei", "ev", "obj", "myth", "leg", "doc", "group", "relig", "serv",
              "ship", "creat", "oth"}
# Person names: the same spelling is routinely read several ways by different
# people, and a single listed reading usually means incomplete data.
PERSON_LIKE = {"surname", "given", "masc", "fem", "person", "unclass", "char"}

# Administrative suffixes.  Admitting every place-like entry is safe but does
# not compile -- it needs 6,304 MultipleSubst lookups against a LookupList
# ceiling near 3,000 (see docs/opentype-notes.md).  Names ending in one of
# these are the subset that actually turns up in running text, addresses and
# datelines, their readings are official, and they cost 2,039 lookups.
ADMIN_SUFFIX = tuple("都道府県市区町村郡")


def is_admin_place(surface: str, ntypes) -> bool:
    return bool(set(ntypes) & PLACE_LIKE) and surface.endswith(ADMIN_SUFFIX)


def parse(path: str, verbose: bool = True) -> list[LexEntry]:
    ents = entity_map(path)
    code = lambda s: ents.get(s, s)  # noqa: E731

    out: list[LexEntry] = []
    n_entries = 0
    for entry in iter_entries(path):
        n_entries += 1
        seq = int(entry.findtext("ent_seq") or 0)
        kebs = []
        for k in entry.findall("k_ele"):
            keb = k.findtext("keb") or ""
            if keb:
                infos = {code(e.text) for e in k.findall("ke_inf") if e.text}
                kebs.append((keb, infos))
        if not kebs:
            continue

        ntypes: set[str] = set()
        for t in entry.findall("trans"):
            for nt in t.findall("name_type"):
                if nt.text:
                    ntypes.add(code(nt.text))
        ntype_t = tuple(sorted(ntypes))

        for rank, r in enumerate(entry.findall("r_ele")):
            reb = r.findtext("reb") or ""
            if not reb:
                continue
            reading = normalize_reading(strip_non_reading(reb))
            if not reading or not all(is_kana(c) for c in reading):
                continue
            r_infos = {code(e.text) for e in r.findall("re_inf") if e.text}
            restr = {e.text for e in r.findall("re_restr") if e.text}
            for keb, k_infos in kebs:
                if restr and keb not in restr:
                    continue
                surface = strip_non_reading(keb)
                if not surface or not any(is_kanji(c) for c in surface):
                    continue
                out.append(
                    LexEntry(
                        surface=surface,
                        reading=reading,
                        pri=0,
                        pos=(),
                        common=False,
                        flags=tuple(sorted(k_infos | r_infos)),
                        seq=seq,
                        rank=rank,
                        misc=(),
                        source="jmnedict",
                        ntype=ntype_t,
                    )
                )
    if verbose:
        print(f"[jmnedict] {n_entries} entries -> {len(out)} (surface, reading) pairs")
    return out


def ambiguity_by_type(entries: list[LexEntry]) -> dict[str, dict]:
    """How often does one spelling have several readings, per name type?

    This is the evidence the inclusion policy is built on: a type whose
    spellings are usually multi-read cannot be trusted even when a particular
    entry lists only one reading.
    """
    by_surface: dict[str, set[str]] = defaultdict(set)
    types_of: dict[str, set[str]] = defaultdict(set)
    for e in entries:
        by_surface[e.surface].add(e.reading)
        types_of[e.surface].update(e.ntype)

    stats: dict[str, Counter] = defaultdict(Counter)
    for surface, readings in by_surface.items():
        for t in types_of[surface] or {"(untyped)"}:
            stats[t]["surfaces"] += 1
            if len(readings) > 1:
                stats[t]["multi_reading"] += 1
    out = {}
    for t, c in stats.items():
        n = c["surfaces"]
        out[t] = {
            "surfaces": n,
            "multi_reading": c["multi_reading"],
            "multi_reading_pct": round(100 * c["multi_reading"] / max(1, n), 2),
        }
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["surfaces"]))


if __name__ == "__main__":
    import json
    import sys

    from .lexicon import save

    src = sys.argv[1] if len(sys.argv) > 1 else "data/raw/JMnedict.xml.gz"
    dst = sys.argv[2] if len(sys.argv) > 2 else "data/normalized/names.jsonl"
    es = parse(src)
    save(es, dst)
    report = ambiguity_by_type(es)
    print(json.dumps(report, ensure_ascii=False, indent=1))
