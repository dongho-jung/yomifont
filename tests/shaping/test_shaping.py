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

from corpus import (ABSTAIN, EXPLICIT, EXPLICIT_ASCII,  # noqa: E402
                    EXPLICIT_MALFORMED, NO_RUBY, POC, SENTENCES,
                    STABILIZATION, STABILIZATION_ABSTAIN)
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
# Explicit Ruby


def _reading(glyphs) -> str:
    return "".join(g.ruby_char for g in glyphs if g.ruby_char is not None)


@pytest.mark.parametrize("text,base_em,reading", EXPLICIT)
def test_explicit_reading(text, base_em, reading):
    """The user's reading is rendered verbatim, with no dictionary consulted."""
    assert _reading(shape_harfbuzz(FONT, text)) == reading, text


@pytest.mark.parametrize("text,base_em,reading", EXPLICIT)
def test_explicit_markup_is_invisible_and_weightless(text, base_em, reading):
    """The three delimiters draw nothing and take no horizontal space."""
    glyphs = shape_harfbuzz(FONT, text)
    blanks = [g for g in glyphs if g.name == "ruby.blank"]
    assert len(blanks) == 3, f"{text}: expected 3 hidden delimiters, got {len(blanks)}"
    assert all(g.advance == 0 for g in blanks)
    assert all(g.advance == 0 for g in glyphs if g.ruby_char is not None)
    if base_em is not None:
        assert total_advance(glyphs) == base_em * 1000, text


@pytest.mark.parametrize("text,base_em,reading", EXPLICIT)
def test_explicit_clusters_cover_source(text, base_em, reading):
    """Copy, select and search still operate on the markup the user typed."""
    clusters = {g.cluster for g in shape_harfbuzz(FONT, text)}
    assert min(clusters) == 0 and max(clusters) < len(text)


@pytest.mark.parametrize("text,base_em,reading", EXPLICIT)
def test_explicit_suppresses_automatic_ruby(text, base_em, reading):
    """Never automatic ruby *and* explicit ruby on the same base."""
    assert _reading(shape_harfbuzz(FONT, text)) == reading, text


def test_explicit_overrides_a_word_the_dictionary_knows():
    assert ruby_runs(shape_harfbuzz(FONT, "東京")) == ["とうきょう"]
    assert _reading(shape_harfbuzz(FONT, "｜東京（エド）")) == "エド"
    assert ruby_runs(shape_harfbuzz(FONT, "宇宙")) == ["うちゅう"]
    assert _reading(shape_harfbuzz(FONT, "｜宇宙（そら）")) == "そら"


def test_automatic_ruby_still_works_around_an_explicit_span():
    glyphs = shape_harfbuzz(FONT, "昨日、｜月（ライト）を見た。")
    assert ruby_runs(glyphs)[0] == "きのう"
    assert "ライト" in "".join(ruby_runs(glyphs))
    # and two explicit spans in a row do not interfere
    assert _reading(shape_harfbuzz(FONT, "｜月（ライト）と｜宇宙（そら）")) == "ライトそら"


@pytest.mark.parametrize("ascii_text,fullwidth_text", EXPLICIT_ASCII)
def test_ascii_syntax_is_identical(ascii_text, fullwidth_text):
    """Both syntaxes must reach the same glyphs, not merely look similar."""
    a = shape_harfbuzz(FONT, ascii_text)
    f = shape_harfbuzz(FONT, fullwidth_text)
    assert [g.name for g in a] == [g.name for g in f], ascii_text


def _markup_hidden(glyphs) -> bool:
    """Did anything the user typed stop being drawn?"""
    return any(g.name == "ruby.blank" for g in glyphs)


def _protected(glyphs) -> bool:
    """Did the base span get claimed, suppressing automatic ruby on it?

    Distinct from `_markup_hidden`: claiming the span is invisible -- the
    duplicate draws exactly like the original -- and it is what the Blink
    fail-safe does on its own when it can see ｜BASE（ but not the reading.
    """
    return any(g.name.startswith("x.") for g in glyphs)


@pytest.mark.parametrize("text,why", EXPLICIT_MALFORMED)
def test_malformed_markup_is_left_alone(text, why):
    """Broken markup stays visible -- never partly transformed.

    Asserted as "nothing the user typed stopped being drawn", not as "the glyph
    stream is the no-GSUB stream", for two reasons. Several of these cases
    contain ordinary words and *automatic* ruby is supposed to keep working on
    them -- 月（ライトという意味） should still read 意味 as いみ. And a
    well-formed prefix legitimately claims its base span (see the Blink
    fail-safe), which is invisible.
    """
    glyphs = shape_harfbuzz(FONT, text)
    assert not _markup_hidden(glyphs), f"{text} ({why}) hid part of the markup"
    for ch in text:
        if ch in "｜|（(）)":
            assert _plain_glyph_names(ch)[0] in [g.name for g in glyphs], \
                f"{text} ({why}): {ch} disappeared"


def test_protected_duplicates_draw_identically():
    """Claiming a base span must be invisible.

    The fail-safe swaps base glyphs for duplicates whenever it sees ｜BASE（,
    including when the reading never arrives. That is only acceptable if the
    duplicate is indistinguishable from the original.
    """
    from fontTools.pens.recordingPen import RecordingPen
    from fontTools.ttLib import TTFont

    font = TTFont(FONT)
    gs = font.getGlyphSet()
    hmtx = font["hmtx"]
    dups = [n for n in font.getGlyphOrder() if n.startswith("x.")]
    assert dups, "expected protected duplicates"
    for name in dups[:400]:
        orig = name[2:]
        assert hmtx[name] == hmtx[orig], name
        a, b = RecordingPen(), RecordingPen()
        gs[name].draw(a)
        gs[orig].draw(b)
        # the duplicate is a one-component composite of the original
        assert a.value and (a.value == b.value
                            or a.value == [("addComponent", (orig, (1, 0, 0, 1, 0, 0)))]), name


def test_blink_failsafe_claims_the_base_from_the_prefix_alone():
    """｜BASE（ with no readable reading must still suppress automatic ruby.

    Blink never shows one rule the whole expression, but it does keep
    ｜BASE（ together (tests/integration/itemize_probe.html). Without this the
    author's ｜宇宙（そら） renders in Chrome as visible markup plus うちゅう --
    the dictionary reading they explicitly replaced.
    """
    # The reading is unusable, so the full expression cannot match. What must
    # not happen is the *base* falling back to its dictionary reading; ruby on
    # the rest of the string (漢字 is an ordinary word) is fine and expected.
    for text, base, suppressed in [("｜宇宙（漢字）", "宇宙", "うちゅう"),
                                   ("｜東京（漢字）", "東京", "とうきょう")]:
        glyphs = shape_harfbuzz(FONT, text)
        assert _protected(glyphs), f"{text}: base span was not claimed"
        assert suppressed not in _reading(glyphs), \
            f"{text} showed {suppressed}, the reading the author replaced"
    # ...and the base still reads normally when it is not annotated
    assert ruby_runs(shape_harfbuzz(FONT, "宇宙")) == ["うちゅう"]
    assert ruby_runs(shape_harfbuzz(FONT, "東京")) == ["とうきょう"]


def test_explicit_ruby_reuses_the_shared_inventory():
    """The same kana in different expressions comes from one glyph family."""
    names = set()
    for text in ["｜月（ライト）", "｜光（ライト）", "｜夜神月（やがみライト）"]:
        for g in shape_harfbuzz(FONT, text):
            if g.ruby_char == "ラ":
                names.add(g.name)
    assert names, "expected ラ ruby glyphs"
    assert all(n.startswith("r.30E9.") for n in names), names


def test_line_break_inside_an_expression_fails_safe():
    """A break splits the expression into two independently shaped halves.

    Neither half can match, so both must render as the literal markup the user
    typed.  What must never happen is a half-transformed result: ruby stranded
    on one line, or a base whose reading went to the next line.
    """
    text = "｜日本語能力試験（にほんごのうりょくしけん）"
    for cut in range(1, len(text)):
        for half in (text[:cut], text[cut:]):
            glyphs = shape_harfbuzz(FONT, half)
            assert not _markup_hidden(glyphs), \
                f"break at {cut} hid markup in {half!r}"
    # The base half may still pick up an *automatic* reading -- that is correct,
    # it is an ordinary word once the markup is gone -- but the delimiters must
    # never vanish, which is what would strand ruby on the wrong line.
    for cut in range(1, len(text)):
        for half in (text[:cut], text[cut:]):
            names = [g.name for g in shape_harfbuzz(FONT, half)]
            for ch in half:
                if ch in "｜（）":
                    assert _plain_glyph_names(ch)[0] in names, (cut, half, ch)


def test_explicit_ruby_needs_no_dictionary():
    """A base string that cannot be in any dictionary still takes a reading."""
    for base, reading in [("超絶暗黒剣", "ダークネスブレード"),
                          ("未知語", "オリジナルヨミ"),
                          # rare kanji, kokuji, and a compound no lexicon has
                          ("淼焱掾", "キンビョウエン"),
                          ("辻凪", "つじなぎ")]:
        text = f"｜{base}（{reading}）"
        assert _reading(shape_harfbuzz(FONT, text)) == reading, text


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
@pytest.mark.parametrize(
    "text", [t for t, _, _ in EXPLICIT] + [t for t, _ in EXPLICIT_MALFORMED]
    + [t for t, _ in EXPLICIT_ASCII])
def test_coretext_matches_harfbuzz_explicit(text):
    hb = shape_harfbuzz(FONT, text)
    ct = shape_coretext(FONT, text)
    assert [g.name for g in ct] == [g.name for g in hb], text
    assert [g.advance for g in ct] == [g.advance for g in hb], text
