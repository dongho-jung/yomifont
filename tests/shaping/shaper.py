"""Shape text with a YomiFont build and decode the ruby back out of the glyphs.

Two backends:

    harfbuzz   uharfbuzz (also what Chrome, Firefox and Android use)
    coretext   tools/ctshape (macOS / Safari / native controls)

Both return the same normalised structure so the tests can assert engine
agreement, which is the point: a font that only works under HarfBuzz has not
demonstrated anything about compatibility.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CTSHAPE = os.path.join(ROOT, "tools", "ctshape", "ctshape")

RUBY_RE = re.compile(r"^r\.([0-9A-F]{4})\.t(m?)(\d+)$")


@dataclass(frozen=True)
class ShapedGlyph:
    name: str
    advance: int
    x: int
    y: int
    cluster: int

    @property
    def ruby_char(self) -> str | None:
        m = RUBY_RE.match(self.name)
        return chr(int(m.group(1), 16)) if m else None

    @property
    def ruby_t(self) -> int | None:
        m = RUBY_RE.match(self.name)
        if not m:
            return None
        return -int(m.group(3)) if m.group(2) else int(m.group(3))


def shape_harfbuzz(font_path: str, text: str) -> list[ShapedGlyph]:
    import uharfbuzz as hb

    blob = hb.Blob.from_file_path(font_path)
    font = hb.Font(hb.Face(blob))
    if not text:
        return []
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf)
    out = []
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        out.append(
            ShapedGlyph(
                name=font.glyph_to_string(info.codepoint),
                advance=pos.x_advance,
                x=pos.x_offset,
                y=pos.y_offset,
                cluster=info.cluster,
            )
        )
    return out


def shape_coretext(font_path: str, text: str) -> list[ShapedGlyph]:
    if not text:
        return []
    if not os.path.exists(CTSHAPE):
        raise RuntimeError("ctshape not built; run scripts/build_tools.sh")
    r = subprocess.run([CTSHAPE, font_path, "100", text],
                       capture_output=True, text=True, check=True)
    data = json.loads(r.stdout)
    return [
        ShapedGlyph(name=g["name"], advance=int(g["adv"]), x=int(g["x"]),
                    y=int(g["y"]), cluster=g["cluster"])
        for g in data["glyphs"]
    ]


def ruby_runs(glyphs: list[ShapedGlyph]) -> list[str]:
    """Consecutive ruby glyphs collapsed into reading strings.

    A run breaks when a non-ruby glyph appears or when t goes backwards, which
    is what separates two ruby groups emitted from the same substitution
    (取 -> と at t=1, then 戻 -> もど at t=8,10).
    """
    runs: list[str] = []
    cur: list[str] = []
    last_t: int | None = None
    for g in glyphs:
        ch = g.ruby_char
        if ch is None:
            if cur:
                runs.append("".join(cur))
                cur, last_t = [], None
            continue
        t = g.ruby_t
        if last_t is not None and t is not None and t - last_t > 2:
            runs.append("".join(cur))
            cur = []
        cur.append(ch)
        last_t = t
    if cur:
        runs.append("".join(cur))
    return runs


def base_text(glyphs: list[ShapedGlyph]) -> list[ShapedGlyph]:
    return [g for g in glyphs if g.ruby_char is None]


def total_advance(glyphs: list[ShapedGlyph]) -> int:
    return sum(g.advance for g in glyphs)
