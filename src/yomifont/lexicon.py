"""The lexical IR shared by JMdict and JMnedict.

The critical field is `seq`, the source dictionary's entry id.  Two readings of
the same surface mean completely different things depending on whether they sit
inside one entry or in two:

    今日   きょう / こんにち     one entry   -> variant readings of one lexeme
    市場   しじょう / いちば     two entries -> two different words

The first is safe to render (pick the prominent reading); the second is not
resolvable without knowing the sentence.  Phase 1 collapsed both into a
priority contest, which is exactly how wrong furigana got emitted.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

# EDRDG markers meaning "this form is not in current use".  An entry carrying
# any of them is not treated as a live competitor when deciding whether a
# surface has one safe reading.
DEAD_MISC = {"arch", "obs", "rare", "dated", "poet", "obsc"}
DEAD_KANJI_INFO = {"iK", "ik", "oK", "rK", "sK", "io"}
DEAD_READING_INFO = {"ik", "ok", "sk", "rk", "gikun"} - {"gikun"}  # gikun is fine


@dataclass(slots=True)
class LexEntry:
    surface: str
    reading: str
    pri: int
    pos: tuple[str, ...]
    common: bool
    flags: tuple[str, ...]
    seq: int                    # source entry id: identity, not a score
    rank: int                   # reading order inside the entry, 0 = most prominent
    misc: tuple[str, ...]
    source: str                 # 'jmdict' | 'jmnedict'
    ntype: tuple[str, ...] = () # JMnedict name types

    @property
    def live(self) -> bool:
        """Is this a form EDRDG considers current?"""
        return not (set(self.misc) & DEAD_MISC or set(self.flags) & DEAD_KANJI_INFO)

    def as_row(self) -> list:
        return [self.surface, self.reading, self.pri, list(self.pos), self.common,
                list(self.flags), self.seq, self.rank, list(self.misc), self.source,
                list(self.ntype)]

    @staticmethod
    def from_row(r: list) -> "LexEntry":
        return LexEntry(r[0], r[1], r[2], tuple(r[3]), r[4], tuple(r[5]), r[6], r[7],
                        tuple(r[8]), r[9], tuple(r[10]))


def save(entries: list[LexEntry], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e.as_row(), ensure_ascii=False, separators=(",", ":")) + "\n")


def load(path: str) -> list[LexEntry]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            out.append(LexEntry.from_row(json.loads(line)))
    return out
