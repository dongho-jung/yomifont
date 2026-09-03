"""Shaping tests against a built YomiFont.

Run with:   pytest tests/ -v
Requires:   dist/YomiFont-Regular.ttf   (scripts/pipeline.py)

The tests assert the architectural claims, not corpus accuracy:

  * ruby glyphs are inserted and are zero-advance
  * the base glyph stream is unchanged (text integrity)
  * cluster values still map every glyph back to the original characters
  * longest match picks the intended rule
  * HarfBuzz and CoreText agree
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from corpus import NO_RUBY, POC, SENTENCES  # noqa: E402
from shaper import (base_text, ruby_runs, shape_coretext,  # noqa: E402
                    shape_harfbuzz, total_advance)

FONT = os.environ.get("YOMIFONT", os.path.join(ROOT, "dist", "YomiFont-Regular.ttf"))

pytestmark = pytest.mark.skipif(
    not os.path.exists(FONT), reason=f"build a font first: {FONT} not found"
)


def _plain_glyph_names(text: str) -> list[str]:
    """What the glyph stream would be with no GSUB at all."""
    from fontTools.ttLib import TTFont

    f = TTFont(FONT, lazy=True)
    cmap = f.getBestCmap()
    return [cmap[ord(c)] for c in text if ord(c) in cmap]


# --------------------------------------------------------------------------
# text integrity: the whole point of doing this in the font


@pytest.mark.parametrize("text,_expected", POC + SENTENCES)
def test_base_glyphs_unchanged(text, _expected):
    """Ruby insertion must not disturb the base glyph run or its advances."""
    glyphs = shape_harfbuzz(FONT, text)
    assert [g.name for g in base_text(glyphs)] == _plain_glyph_names(text)


@pytest.mark.parametrize("text,_expected", POC + SENTENCES)
def test_ruby_is_zero_advance(text, _expected):
    glyphs = shape_harfbuzz(FONT, text)
    for g in glyphs:
        if g.ruby_char is not None:
            assert g.advance == 0, f"ruby glyph {g.name} has advance {g.advance}"


@pytest.mark.parametrize("text,_expected", POC + SENTENCES)
def test_line_width_matches_plain_text(text, _expected):
    """Ruby must not change how much horizontal space the text occupies."""
    glyphs = shape_harfbuzz(FONT, text)
    n_full = len(_plain_glyph_names(text))
    assert total_advance(glyphs) == sum(g.advance for g in base_text(glyphs))
    assert len(base_text(glyphs)) == n_full


@pytest.mark.parametrize("text,_expected", POC + SENTENCES)
def test_clusters_cover_source(text, _expected):
    """Every glyph maps back to a character index, so selection/copy still work."""
    glyphs = shape_harfbuzz(FONT, text)
    clusters = {g.cluster for g in glyphs}
    assert clusters, text
    assert max(clusters) < len(text)
    assert min(clusters) == 0


# --------------------------------------------------------------------------
# ruby content


@pytest.mark.parametrize("text,expected", POC)
def test_poc_readings(text, expected):
    runs = ruby_runs(shape_harfbuzz(FONT, text))
    assert runs == [r for _, r in expected], f"{text}: got {runs}"


@pytest.mark.parametrize("text,expected", SENTENCES)
def test_sentence_readings(text, expected):
    runs = ruby_runs(shape_harfbuzz(FONT, text))
    assert runs == [r for _, r in expected], f"{text}: got {runs}"


@pytest.mark.parametrize("text", NO_RUBY)
def test_no_ruby_for_kana_only(text):
    glyphs = shape_harfbuzz(FONT, text)
    assert [g for g in glyphs if g.ruby_char is not None] == []


def test_longest_match_beats_prefix():
    """日本語 must not decompose into 日本 + 語."""
    assert ruby_runs(shape_harfbuzz(FONT, "日本")) == ["にほん"]
    assert ruby_runs(shape_harfbuzz(FONT, "日本語")) == ["にほんご"]
    assert ruby_runs(shape_harfbuzz(FONT, "日本人")) == ["にほんじん"]


def test_okurigana_context_changes_reading():
    assert ruby_runs(shape_harfbuzz(FONT, "行く")) == ["い"]
    assert ruby_runs(shape_harfbuzz(FONT, "行う")) == ["おこな"]


def test_ruby_glyphs_are_reused_not_per_word():
    """The reusable-ruby claim, asserted mechanically.

    き appears in きょう (今日) and in きょうと (京都) at different slots; the
    same kana must resolve to a bounded set of glyphs, not a per-word one.
    """
    names = set()
    for text in ["今日", "京都", "東京", "銀行", "教室", "急行"]:
        for g in shape_harfbuzz(FONT, text):
            if g.ruby_char == "き":
                names.add(g.name)
    assert names, "expected き ruby glyphs"
    # every one is a positional variant of the same base kana
    assert all(n.startswith("r.304D.t") for n in names)


# --------------------------------------------------------------------------
# engine agreement


@pytest.mark.skipif(sys.platform != "darwin", reason="CoreText is macOS only")
@pytest.mark.parametrize("text,_expected", POC + SENTENCES)
def test_coretext_matches_harfbuzz(text, _expected):
    hb = shape_harfbuzz(FONT, text)
    ct = shape_coretext(FONT, text)
    assert [g.name for g in ct] == [g.name for g in hb], text
    assert [g.advance for g in ct] == [g.advance for g in hb], text
