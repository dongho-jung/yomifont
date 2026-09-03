"""Reference implementation of what the compiled GSUB does.

This mirrors the shaping semantics exactly:

  * scan the text left to right
  * at each position, consider only rules whose first character matches
  * try them longest-first (this is the rule order inside a ChainSubRuleSet)
  * on a match, emit its ruby groups and jump past the whole matched input

Having this in Python lets us measure reading accuracy over a large corpus
without building a font for every experiment, and lets the shaping tests assert
that the real font agrees with the reference.
"""
from __future__ import annotations

from dataclasses import dataclass

from .rules import Rule


@dataclass(slots=True)
class Match:
    start: int
    length: int          # characters of input consumed
    groups: tuple[tuple[int, int, str], ...]  # offsets relative to `start`
    rule: Rule


class RuleIndex:
    """First-character keyed index, each bucket ordered longest-first."""

    def __init__(self, rules: list[Rule]):
        buckets: dict[str, list[Rule]] = {}
        for r in rules:
            buckets.setdefault(r.seq[0], []).append(r)
        for v in buckets.values():
            v.sort(key=lambda r: (-len(r.seq), r.seq))
        self.buckets = buckets

    def __len__(self) -> int:
        return sum(len(v) for v in self.buckets.values())

    @property
    def n_first_chars(self) -> int:
        return len(self.buckets)

    def match_at(self, text: str, i: int) -> Rule | None:
        for r in self.buckets.get(text[i], ()):
            n = len(r.seq)
            if text.startswith(r.seq, i):
                return r
        return None

    def apply(self, text: str) -> list[Match]:
        out: list[Match] = []
        i = 0
        n = len(text)
        while i < n:
            r = self.match_at(text, i)
            if r is None:
                i += 1
                continue
            out.append(Match(i, len(r.seq), r.groups, r))
            i += len(r.seq)
        return out

    def apply_segmented(self, text: str) -> list[Match]:
        """Shape each maximal same-script run independently.

        This models Blink: Chrome itemises a text node into script runs before
        handing anything to HarfBuzz, so a GSUB rule can never match across a
        Han <-> Kana boundary.  Measured against Chrome 151, every output of
        this function reproduces what the browser actually draws.
        WebKit/CoreText does *not* do this and matches `apply`.
        """
        out: list[Match] = []
        for start, end in script_runs(text):
            for m in self.apply(text[start:end]):
                out.append(Match(m.start + start, m.length, m.groups, m.rule))
        return out


def _script(ch: str) -> str:
    from .kana import is_kana, is_kanji

    if is_kanji(ch):
        return "Hani"
    if is_kana(ch):
        return "Kana"
    return "Other"


def script_runs(text: str) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        s = _script(text[i])
        j = i + 1
        while j < len(text) and _script(text[j]) == s:
            j += 1
        runs.append((i, j))
        i = j
    return runs


def render(text: str, matches: list[Match]) -> str:
    """Debug view: ruby in brackets after the span it covers."""
    pieces = []
    pos = 0
    for m in matches:
        pieces.append(text[pos : m.start])
        seg = text[m.start : m.start + m.length]
        covered = []
        last = 0
        for gs, gl, rd in m.groups:
            covered.append(seg[last:gs])
            covered.append(f"{seg[gs:gs+gl]}[{rd}]")
            last = gs + gl
        covered.append(seg[last:])
        pieces.append("".join(covered))
        pos = m.start + m.length
    pieces.append(text[pos:])
    return "".join(pieces)


def token_reading(text: str, start: int, end: int, matches: list[Match]) -> tuple[str | None, str]:
    """Reconstruct the reading YomiFont implies for text[start:end].

    Returns (reading, status) where status is one of
    'ok' | 'no_ruby' | 'partial' | 'straddle'.
    """
    covering = [m for m in matches if m.start < end and m.start + m.length > start]
    if not covering:
        return None, "no_ruby"
    if any(m.start < start or m.start + m.length > end for m in covering):
        return None, "straddle"

    # character -> reading contributed
    out: list[str] = []
    pos = start
    for m in covering:
        if m.start > pos:
            out.append(text[pos : m.start])
        seg = text[m.start : m.start + m.length]
        last = 0
        for gs, gl, rd in m.groups:
            out.append(seg[last:gs])
            out.append(rd)
            last = gs + gl
        out.append(seg[last:])
        pos = m.start + m.length
    if pos < end:
        out.append(text[pos:end])
    return "".join(out), "ok"
