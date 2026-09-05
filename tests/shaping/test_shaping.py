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

from corpus import (ABSTAIN, NO_RUBY, POC,  # noqa: E402
                    PUNCTUATION_INTACT, SENTENCES, STABILIZATION,
                    STABILIZATION_ABSTAIN)
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


@pytest.mark.parametrize("text,_expected", POC + SENTENCES + ABSTAIN)
def test_base_glyphs_unchanged(text, _expected):
    """Ruby insertion must not disturb the base glyph run or its advances."""
    glyphs = shape_harfbuzz(FONT, text)
    assert [g.name for g in base_text(glyphs)] == _plain_glyph_names(text)


@pytest.mark.parametrize("text,_expected", POC + SENTENCES + ABSTAIN)
def test_ruby_is_zero_advance(text, _expected):
    glyphs = shape_harfbuzz(FONT, text)
    for g in glyphs:
        if g.ruby_char is not None:
            assert g.advance == 0, f"ruby glyph {g.name} has advance {g.advance}"


@pytest.mark.parametrize("text,_expected", POC + SENTENCES + ABSTAIN)
def test_line_width_matches_plain_text(text, _expected):
    """Ruby must not change how much horizontal space the text occupies."""
    glyphs = shape_harfbuzz(FONT, text)
    n_full = len(_plain_glyph_names(text))
    assert total_advance(glyphs) == sum(g.advance for g in base_text(glyphs))
    assert len(base_text(glyphs)) == n_full


@pytest.mark.parametrize("text,_expected", POC + SENTENCES + ABSTAIN)
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
    assert runs == expected, f"{text}: got {runs}"


@pytest.mark.parametrize("text,expected", SENTENCES)
def test_sentence_readings(text, expected):
    runs = ruby_runs(shape_harfbuzz(FONT, text))
    assert runs == expected, f"{text}: got {runs}"


@pytest.mark.parametrize("text,why", ABSTAIN)
def test_abstains_on_ambiguous(text, why):
    """Precision-first: an undetermined reading must render nothing at all."""
    glyphs = shape_harfbuzz(FONT, text)
    ruby = [g.name for g in glyphs if g.ruby_char is not None]
    assert ruby == [], f"{text} ({why}) should have no ruby, got {ruby}"


@pytest.mark.parametrize("text", NO_RUBY)
def test_no_ruby_for_kana_only(text):
    glyphs = shape_harfbuzz(FONT, text)
    assert [g for g in glyphs if g.ruby_char is not None] == []


@pytest.mark.parametrize("text,expected", STABILIZATION)
def test_stabilization_regressions(text, expected):
    runs = ruby_runs(shape_harfbuzz(FONT, text))
    assert runs == expected, f"{text}: got {runs}"


@pytest.mark.parametrize("text,why", STABILIZATION_ABSTAIN)
def test_stabilization_abstentions(text, why):
    """Wrong automatic ruby is worse than none: these must render nothing."""
    ruby = [g.name for g in shape_harfbuzz(FONT, text) if g.ruby_char is not None]
    assert ruby == [], f"{text} ({why}) should have no ruby, got {ruby}"


def test_no_single_character_automatic_rules():
    """The single-kanji fallback is gone, and must stay gone.

    A lone kanji is polyphonic and nothing a shaping engine can see resolves
    it, so 月 gets no ruby rather than one of つき / げつ / がつ.
    """
    import json
    rules = [json.loads(l) for l in open(
        os.path.join(ROOT, "data", "normalized", "rules.jsonl"), encoding="utf-8")]
    singles = [r for r in rules if len(r[0]) == 1 and r[1]]
    assert singles == [], f"{len(singles)} single-character ruby rules leaked in"


def test_no_oversized_single_subst():
    """A SingleSubst fmt 2 reaches its Coverage past the substitute array.

    Over ~32,765 mappings that Offset16 cannot reach, and fontTools has no
    splitter for lookup type 1 -- the build simply stops. Keep every subtable
    well inside it. See docs/opentype-notes.md.
    """
    from fontTools.ttLib import TTFont

    font = TTFont(FONT, lazy=True)
    worst = 0
    for lk in font["GSUB"].table.LookupList.Lookup:
        for st in lk.SubTable:
            inner = getattr(st, "ExtSubTable", st)
            if getattr(inner, "LookupType", lk.LookupType) == 1 or \
               type(inner).__name__ == "SingleSubst":
                worst = max(worst, len(getattr(inner, "mapping", {}) or {}))
    assert 0 < worst <= 32_000, f"largest SingleSubst subtable has {worst} mappings"


def test_longest_match_beats_prefix():
    """日本語 must not decompose into 日本 + 語."""
    assert ruby_runs(shape_harfbuzz(FONT, "日本")) == ["にほん"]
    assert ruby_runs(shape_harfbuzz(FONT, "日本語")) == ["にほんご"]
    assert ruby_runs(shape_harfbuzz(FONT, "日本人")) == ["にほんじん"]


def test_okurigana_context_changes_reading():
    assert ruby_runs(shape_harfbuzz(FONT, "行く")) == ["い"]
    assert ruby_runs(shape_harfbuzz(FONT, "行う")) == ["おこな"]


def test_ruby_glyphs_are_reused_not_per_word():
    """The reusable-ruby claim, asserted mechanically."""
    names = set()
    for text in ["今日", "京都", "東京", "銀行", "教室", "急行"]:
        for g in shape_harfbuzz(FONT, text):
            if g.ruby_char == "き":
                names.add(g.name)
    assert names, "expected き ruby glyphs"
    assert all(n.startswith("r.304D.") for n in names)


def test_ruby_groups_do_not_collide():
    """Adjacent ruby groups must stay visually separate.

    This is the Phase 1 defect: 京都大学病院 ran its three readings together
    with -0.068 em between groups.
    """
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.ttLib import TTFont

    font = TTFont(FONT)
    gs = font.getGlyphSet()
    for text in ["京都大学病院", "国際交流基金東京", "日本語学校",
                 "私は昨日東京へ行きました。"]:
        pen, groups, cur = 0, [], []
        for g in shape_harfbuzz(FONT, text):
            bp = BoundsPen(gs)
            gs[g.name].draw(bp)
            if g.ruby_char is not None:
                if bp.bounds:
                    cur.append((pen + bp.bounds[0], pen + bp.bounds[2]))
            elif cur:
                groups.append(cur)
                cur = []
            pen += g.advance
        if cur:
            groups.append(cur)
        spans = [(min(a for a, _ in g), max(b for _, b in g)) for g in groups]
        for i in range(len(spans) - 1):
            gap = spans[i + 1][0] - spans[i][1]
            assert gap > 0, f"{text}: ruby groups {i} and {i+1} overlap by {-gap}"


def test_no_gpos_table():
    from fontTools.ttLib import TTFont

    assert "GPOS" not in TTFont(FONT, lazy=True)


# --------------------------------------------------------------------------
# Punctuation integrity
#
# Author-supplied ruby used ｜ | （ ( ） ) as delimiters and hid them from the
# output.  With the feature gone they are ordinary characters again, and the
# risk in removing a feature is leaving half of it behind -- a stray rule that
# still eats a bracket.  These assert the delimiters are drawn, take their
# normal width, and pick up no ruby of their own.


@pytest.mark.parametrize("text", PUNCTUATION_INTACT)
def test_punctuation_reaches_the_reader(text):
    glyphs = shape_harfbuzz(FONT, text)
    names = [g.name for g in glyphs]
    assert "ruby.blank" not in names, f"{text}: something was hidden"
    for ch in text:
        if ch in "｜|（(）)《》":
            assert _plain_glyph_names(ch)[0] in names, f"{text}: {ch} disappeared"


@pytest.mark.parametrize("text", PUNCTUATION_INTACT)
def test_punctuation_keeps_its_advance(text):
    """No delimiter is weightless.  Automatic ruby on the words is fine."""
    delims = {_plain_glyph_names(ch)[0] for ch in text if ch in "｜|（(）)《》"}
    for g in shape_harfbuzz(FONT, text):
        if g.name in delims:
            assert g.advance > 0, f"{text}: {g.name} lost its advance"


# --------------------------------------------------------------------------
# engine agreement


@pytest.mark.skipif(sys.platform != "darwin", reason="CoreText is macOS only")
@pytest.mark.parametrize("text,_expected", POC + SENTENCES + ABSTAIN)
def test_coretext_matches_harfbuzz(text, _expected):
    hb = shape_harfbuzz(FONT, text)
    ct = shape_coretext(FONT, text)
    assert [g.name for g in ct] == [g.name for g in hb], text
    assert [g.advance for g in ct] == [g.advance for g in hb], text


@pytest.mark.skipif(sys.platform != "darwin", reason="CoreText is macOS only")
@pytest.mark.parametrize("text", PUNCTUATION_INTACT)
def test_coretext_matches_harfbuzz_punctuation(text):
    hb = shape_harfbuzz(FONT, text)
    ct = shape_coretext(FONT, text)
    assert [g.name for g in ct] == [g.name for g in hb], text
    assert [g.advance for g in ct] == [g.advance for g in hb], text
