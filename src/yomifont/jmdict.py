"""JMdict -> compact lexical IR.

We keep only what can influence *reading selection*:

    surface        the orthographic form (keb)
    reading        hiragana reading (reb, katakana folded)
    pri            integer priority derived from ke_pri/re_pri
    pos            part-of-speech codes, kept only for conjugation generation
    flags          irregular/rare/search-only markers we want to filter on

Glosses, examples, cross-references, dialect, field, language-of-origin and
everything else in JMdict is dropped at parse time -- it never reaches the font.

JMdict is CC BY-SA 4.0 (EDRDG).  See docs/licensing.md.
"""
from __future__ import annotations

import gzip
import json
import os
import re
from dataclasses import dataclass, field
from typing import Iterator
from xml.etree import ElementTree as ET

from .kana import is_kana, is_kanji, normalize_reading, strip_non_reading
from .lexicon import LexEntry, load, save  # noqa: F401  (re-exported)

# ke_pri / re_pri values, mapped to a coarse frequency score.  Lower news1/ichi1
# ranks mean more common.  nfXX are frequency buckets from a newspaper corpus
# (nf01 = most common 500 words, nf48 = least).
PRI_SCORE = {
    "news1": 40, "news2": 20,
    "ichi1": 40, "ichi2": 20,
    "spec1": 40, "spec2": 20,
    "gai1": 25, "gai2": 12,
}

# ke_inf / re_inf codes that mean "do not use this as a default reading"
BAD_KANJI_INFO = {"iK", "ik", "oK", "rK", "sK"}   # irregular/outdated/rare/search-only
BAD_READING_INFO = {"ik", "ok", "sk", "rk"}

NF_RE = re.compile(r"^nf(\d+)$")
ENTITY_RE = re.compile(rb'<!ENTITY\s+([A-Za-z0-9_-]+)\s+"([^"]*)">')

# JMdict lists an entry's readings in order of prominence.  That editorial
# signal is more reliable than re_pri for picking a *default* reading:
# 今日 has きょう first with only `ichi1`, while こんにち carries
# ichi1+news1+nf02 because the newspaper corpus is full of 今日は and formal
# 今日的.  In running text きょう is what a reader wants.
FIRST_READING_BONUS = 400
READING_RANK_STEP = 200


def _pri_score(pri_tags: list[str]) -> tuple[int, bool]:
    """Return (score, is_common).  Higher score = more common."""
    score = 0
    common = False
    for t in pri_tags:
        if t in PRI_SCORE:
            score += PRI_SCORE[t]
            common = True
        else:
            m = NF_RE.match(t)
            if m:
                # nf01 -> 48, nf48 -> 1
                score += max(0, 49 - int(m.group(1)))
                common = True
    return score, common


def _open(path: str):
    return gzip.open(path, "rb") if path.endswith(".gz") else open(path, "rb")


def entity_map(path: str) -> dict[str, str]:
    """Map JMdict's expanded entity text back to its short code.

    expat expands `&v5k;` to "Godan verb with `ku' ending" because the DTD is
    inline, so we recover the codes by reading the DTD ourselves.
    """
    out: dict[str, str] = {}
    with _open(path) as fh:
        head = fh.read(400_000)
    for name, text in ENTITY_RE.findall(head):
        out[text.decode("utf-8")] = name.decode("utf-8")
    return out


def iter_entries(path: str) -> Iterator[ET.Element]:
    """Stream <entry> elements without holding the 63MB tree in memory."""
    with _open(path) as fh:
        for event, elem in ET.iterparse(fh, events=("end",)):
            if elem.tag == "entry":
                yield elem
                elem.clear()


def parse(path: str, verbose: bool = True) -> list[LexEntry]:
    ents = entity_map(path)
    code = lambda s: ents.get(s, s)  # noqa: E731

    out: list[LexEntry] = []
    n_entries = 0
    for entry in iter_entries(path):
        n_entries += 1
        kebs: list[tuple[str, set[str], int, bool]] = []
        for k in entry.findall("k_ele"):
            keb = k.findtext("keb") or ""
            if not keb:
                continue
            infos = {code(e.text) for e in k.findall("ke_inf") if e.text}
            score, common = _pri_score([e.text for e in k.findall("ke_pri") if e.text])
            kebs.append((keb, infos, score, common))
        if not kebs:
            continue  # kana-only entry: nothing to put ruby on

        seq = int(entry.findtext("ent_seq") or 0)

        # POS is unioned over senses, but `misc` must NOT be: it is a
        # SENSE-level marker.  Unioning it killed 僕/ぼく (one archaic sense
        # among several), 難しい, 通る, 少女, 大丈夫, 国 and 子, which then
        # lost their readings to obscure competitors.  An entry counts as dead
        # only when EVERY sense is marked dead, so we keep the intersection.
        pos: set[str] = set()
        sense_miscs: list[set[str]] = []
        for sense in entry.findall("sense"):
            for p in sense.findall("pos"):
                if p.text:
                    pos.add(code(p.text))
            sense_miscs.append({code(m.text) for m in sense.findall("misc") if m.text})
        pos_t = tuple(sorted(pos))
        misc_t = tuple(sorted(set.intersection(*sense_miscs))) if sense_miscs else ()

        for rank, r in enumerate(entry.findall("r_ele")):
            reb = r.findtext("reb") or ""
            if not reb:
                continue
            if r.find("re_nokanji") is not None:
                continue
            r_infos = {code(e.text) for e in r.findall("re_inf") if e.text}
            if r_infos & BAD_READING_INFO:
                continue
            reading = normalize_reading(strip_non_reading(reb))
            if not reading or not all(is_kana(c) for c in reading):
                continue
            r_score, r_common = _pri_score([e.text for e in r.findall("re_pri") if e.text])
            restr = {e.text for e in r.findall("re_restr") if e.text}

            for keb, k_infos, k_score, k_common in kebs:
                if restr and keb not in restr:
                    continue
                if k_infos & BAD_KANJI_INFO:
                    continue
                surface = strip_non_reading(keb)
                if not surface or not any(is_kanji(c) for c in surface):
                    continue
                flags = tuple(sorted(k_infos | r_infos))
                prominence = max(0, FIRST_READING_BONUS - READING_RANK_STEP * rank)
                out.append(
                    LexEntry(
                        surface=surface,
                        reading=reading,
                        pri=k_score + r_score + prominence,
                        pos=pos_t,
                        common=k_common or r_common,
                        flags=flags,
                        seq=seq,
                        rank=rank,
                        misc=misc_t,
                        source="jmdict",
                    )
                )
    if verbose:
        print(f"[jmdict] {n_entries} entries -> {len(out)} (surface, reading) pairs")
    return out


def dedupe(entries: list[LexEntry]) -> list[LexEntry]:
    """Collapse duplicates within one entry, keeping the best rank.

    Duplicates ACROSS entries are deliberately preserved: entry identity is
    what the safety classifier uses to tell 今日 (one entry, two readings)
    apart from 市場 (two entries, two readings).
    """
    best: dict[tuple[int, str, str], LexEntry] = {}
    for e in entries:
        k = (e.seq, e.surface, e.reading)
        prev = best.get(k)
        if prev is None or e.rank < prev.rank:
            best[k] = e
    return list(best.values())


if __name__ == "__main__":
    import sys

    src = sys.argv[1] if len(sys.argv) > 1 else "data/raw/JMdict_e.gz"
    dst = sys.argv[2] if len(sys.argv) > 2 else "data/normalized/lexicon.jsonl"
    ents = dedupe(parse(src))
    print(f"[jmdict] {len(ents)} unique (surface, reading) pairs")
    save(ents, dst)
    print(f"[jmdict] wrote {dst} ({os.path.getsize(dst) / 1e6:.1f} MB)")
