#!/usr/bin/env python3
"""Build the font for itemize_probe.html: where does an engine split runs?

    PYTHONPATH=src ./tests/integration/make_itemize_font.py dist/Itemize.ttf

The question this answers is narrow and mechanical: **given a sequence of
characters, does one GSUB rule get to see all of them at once?**  An engine
that itemises text into script runs before shaping will hand the shaper two
buffers instead of one, and no rule can match across the seam.

Method.  For every candidate sequence, the font carries one ChainContextSubst
rule whose input is exactly that sequence of glyphs and whose only action is to
replace the *first* glyph with a zero-advance blank.  So:

    the whole sequence reached GSUB in one run  ->  the text is 1 em narrower
    it was split                                ->  the text is its full width

That is a binary, DOM-observable signal that needs no canvas, no glyph
inspection and no rasteriser.  Every character used appears in the font, so a
split can never be blamed on font fallback.

`CASES` is generated rather than written out, so adding a candidate separator
adds it to every family at once.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fontTools import subset  # noqa: E402
from fontTools.ttLib import TTFont, newTable  # noqa: E402
from fontTools.ttLib.tables import otTables as ot  # noqa: E402
from fontTools.ttLib.tables._g_l_y_f import Glyph  # noqa: E402
from fontTools.pens.ttGlyphPen import TTGlyphPen  # noqa: E402

from yomifont import gsub as gsub_mod  # noqa: E402

BASE_FONT = "data/raw/NotoSansJP-Regular.ttf"

# Representatives of each script, all present in Noto Sans JP.
HAN, HAN2 = "月", "日"
HIRA, KATA, LATIN, DIGIT = "つ", "ラ", "A", "1"

# Candidate separators: (label, string, what it is)
SEPARATORS = [
    ("none",        "",        "direct transition, no separator"),
    # the two syntaxes already shipping
    ("FW_BAR",      "｜",      "U+FF5C fullwidth vertical line, Common"),
    ("ASCII_BAR",   "|",       "U+007C vertical line, Common"),
    ("FW_PAREN",    "（",      "U+FF08 fullwidth left paren, Common"),
    ("ASCII_PAREN", "(",       "U+0028 left paren, Common"),
    # other plausible visible syntaxes
    ("FW_COLON",    "：",      "U+FF1A fullwidth colon, Common"),
    ("ASCII_COLON", ":",       "U+003A colon, Common"),
    ("FW_SLASH",    "／",      "U+FF0F fullwidth solidus, Common"),
    ("ASCII_SLASH", "/",       "U+002F solidus, Common"),
    ("FW_BRACKET",  "［",      "U+FF3B fullwidth left square bracket, Common"),
    ("ASCII_BRACK", "[",       "U+005B left square bracket, Common"),
    ("FW_BRACE",    "｛",      "U+FF5B fullwidth left curly, Common"),
    ("FW_LT",       "＜",      "U+FF1C fullwidth less-than, Common"),
    ("CJK_COMMA",   "、",      "U+3001 ideographic comma, Common"),
    ("MIDDLE_DOT",  "・",      "U+30FB katakana middle dot, Common"),
    ("PROLONG",     "ー",      "U+30FC prolonged sound mark, Common"),
    ("IDEO_SPACE",  "　",      "U+3000 ideographic space, Common"),
    ("SPACE",       " ",       "U+0020 space, Common"),
    ("LOWLINE",     "_",       "U+005F low line, Common"),
    # invisible Common-script formatting characters
    ("ZWSP",        "​",  "U+200B zero width space, Common"),
    ("ZWNJ",        "‌",  "U+200C zero width non-joiner, Common"),
    ("ZWJ",         "‍",  "U+200D zero width joiner, Common"),
    ("WORD_JOINER", "⁠",  "U+2060 word joiner, Common"),
    # Inherited script: these take the script of what precedes them
    ("CGJ",         "͏",  "U+034F combining grapheme joiner, Inherited"),
    ("VS1",         "︀",  "U+FE00 variation selector 1, Inherited"),
    ("VS15",        "︎",  "U+FE0E text presentation selector, Inherited"),
    # Private Use Area: script is Unknown/Zzzz
    ("PUA_E000",    "",  "U+E000 private use, Unknown"),
    ("PUA_F8FF",    "",  "U+F8FF private use, Unknown"),
]

# Two-character transitions, to separate "the separator broke it" from
# "these two scripts never share a run".
TRANSITIONS = [
    ("Han_Han",      HAN + HAN2),
    ("Han_Hira",     HAN + HIRA),
    ("Han_Kata",     HAN + KATA),
    ("Han_Latin",    HAN + LATIN),
    ("Han_Digit",    HAN + DIGIT),
    ("Hira_Han",     HIRA + HAN),
    ("Kata_Han",     KATA + HAN),
    ("Hira_Kata",    HIRA + KATA),
    ("Kata_Hira",    KATA + HIRA),
]


def build_cases():
    """[(label, text, note)] -- every sequence whose run-integrity we test."""
    cases = [(f"transition/{name}", text, "bare script transition")
             for name, text in TRANSITIONS]
    for label, sep, note in SEPARATORS:
        # Han SEP Katakana: the shape explicit ruby actually needs
        cases.append((f"han_sep_kata/{label}", HAN + sep + KATA, note))
        # Han SEP Hiragana
        cases.append((f"han_sep_hira/{label}", HAN + sep + HIRA, note))
        # Kana SEP Kana: the control that already works in every engine
        cases.append((f"hira_sep_kata/{label}", HIRA + sep + KATA, note))
        # the full five-part expression shape, with the candidate as opener
        if sep:
            cases.append((f"expr/{label}", sep + HAN + sep + KATA + sep, note))
    # The prefix an explicit-ruby expression leaves in the *first* Blink run
    # once the kana have been split off. If this is one run, the font can still
    # see the marker and the base, and can suppress automatic ruby on it even
    # when it cannot render the reading.
    for label, sep, note in SEPARATORS:
        if not sep:
            continue
        cases.append((f"prefix/{label}", sep + HAN + sep, note))
    cases.append(("prefix/FW_BAR_2han", "｜" + HAN + HAN2 + "（", "marker + 2 Han + open"))
    cases.append(("prefix/bar_open_only", "｜" + HAN + "（", "marker + Han + open"))
    cases.append(("prefix/ascii_bar_open", "|" + HAN + "(", "ascii marker + Han + open"))
    # a PUA-only transport: does an all-PUA tail stay with the Han?
    # Which side does a Common delimiter land on when it has a neighbour on
    # each side? Do NOT add a case whose text is a prefix of another case's
    # text: the probe reads "one em narrower" as "the rule fired", and a
    # shorter rule firing inside a longer string is indistinguishable. Adding
    # 月（ made 月（ラ report SAME_RUN when it is not.
    # Does a Han-script marker escape absorption by a preceding kana run?
    # ｜ is Common and joins whatever precedes it, which is why run 1 loses its
    # marker after kana. An ideograph starts its own run instead -- if these
    # SPLIT, a Han marker fixes it.
    cases.append(("marker/hira_then_iter", HIRA + "々", "Hiragana + 々 (Han)"))
    cases.append(("marker/kata_then_iter", KATA + "々", "Katakana + 々 (Han)"))
    cases.append(("marker/hira_then_close", HIRA + "〆", "Hiragana + 〆 (Han)"))
    cases.append(("marker/hira_then_bar", HIRA + "｜", "Hiragana + ｜ (Common)"))
    cases.append(("marker/iter_then_han", "々" + HAN, "々 + Han"))
    # Easier-to-type candidates for the non-absorbable leading marker, and the
    # Aozora ruby delimiters 《》 which would remove the need for a trailing one.
    for lbl, ch, note in [("zero", "〇", "U+3007 ideographic zero, type まる"),
                          ("maru", "◯", "U+25EF large circle"),
                          ("kome", "※", "U+203B reference mark, type こめ"),
                          ("geta", "〓", "U+3013 geta mark"),
                          ("dbl_open", "《", "U+300A, Aozora ruby open"),
                          ("dbl_close", "》", "U+300B, Aozora ruby close")]:
        cases.append((f"cand/hira_then_{lbl}", HIRA + ch, "after hiragana: " + note))
        cases.append((f"cand/{lbl}_then_han", ch + HAN, "before Han: " + note))
    cases.append(("cand/kata_then_dblclose", KATA + "》", "Katakana + 》"))
    cases.append(("side/close_with_kata", KATA + "）", "Katakana + close paren"))
    cases.append(("side/bar_with_kata", KATA + "｜", "Katakana + fullwidth bar"))
    cases.append(("pua/han_pua3", HAN + "", "Han + 3 PUA"))
    cases.append(("pua/han_pua_kata", HAN + "" + KATA, "Han + PUA + Katakana"))
    cases.append(("pua/pua_han_pua", "" + HAN + "", "PUA + Han + PUA"))
    return cases


def drop_overlapping(cases):
    """Remove cases another case's text sits inside.

    The probe reads "one em narrower" as "this case's rule fired", and it
    cannot tell that apart from a *shorter* case's rule firing on a substring.
    ｜月｜ is a prefix of ｜月｜ラ｜, so once both carry rules the longer one
    reports SAME_RUN whatever Blink did with it -- which is how 月（ラ briefly
    looked like it shared a run. Keep the shorter, more primitive measurement.
    """
    texts = {t for _, t, _ in cases}
    kept, dropped = [], []
    for label, text, note in cases:
        if any(other != text and other in text for other in texts):
            dropped.append(label)
        else:
            kept.append((label, text, note))
    if dropped:
        print(f"dropped {len(dropped)} unmeasurable cases (another case's text "
              f"is a substring): {', '.join(sorted(dropped)[:6])}"
              f"{' …' if len(dropped) > 6 else ''}")
    return kept


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "dist/Itemize.ttf"
    cases = drop_overlapping(build_cases())

    chars = set()
    for _, text, _ in cases:
        chars.update(text)
    font = TTFont(BASE_FONT)
    opts = subset.Options()
    opts.layout_features = []
    opts.glyph_names = True
    opts.notdef_outline = True
    ss = subset.Subsetter(options=opts)
    ss.populate(text="".join(sorted(c for c in chars if c.isprintable()))
                + HAN + HAN2 + HIRA + KATA + LATIN + DIGIT)
    ss.subset(font)

    glyf, hmtx, cmap_best = font["glyf"], font["hmtx"], font.getBestCmap()
    order = list(font.getGlyphOrder())
    new = []

    def ensure(ch: str) -> str:
        """Every test character must exist in this font, or a 'split' could
        just be font fallback picking a different face."""
        cp = ord(ch)
        if cp in cmap_best:
            return cmap_best[cp]
        name = "test.%04X" % cp
        if name not in glyf.glyphs:
            # a visible-but-narrow mark, so a missing substitution is obvious
            pen = TTGlyphPen(None)
            pen.moveTo((40, 0)); pen.lineTo((120, 0))
            pen.lineTo((120, 700)); pen.lineTo((40, 700)); pen.closePath()
            glyf.glyphs[name] = pen.glyph()
            hmtx.metrics[name] = (160, 40)
            if "vmtx" in font:
                font["vmtx"].metrics[name] = (1000, 0)
            new.append(name)
        return name

    gname = {}
    for ch in sorted(chars):
        gname[ch] = ensure(ch)

    blank = "probe.blank"
    g = Glyph(); g.numberOfContours = 0
    g.xMin = g.yMin = g.xMax = g.yMax = 0
    glyf.glyphs[blank] = g
    hmtx.metrics[blank] = (0, 0)
    if "vmtx" in font:
        font["vmtx"].metrics[blank] = (1000, 0)
    new.append(blank)

    font.setGlyphOrder(order + new)
    font["maxp"].numGlyphs = len(font.getGlyphOrder())
    for n in new:
        if glyf.glyphs[n].numberOfContours:
            glyf.glyphs[n].recalcBounds(glyf)

    # add the new characters to cmap so the browser can actually reach them
    for table in font["cmap"].tables:
        if table.isUnicode():
            for ch in sorted(chars):
                table.cmap.setdefault(ord(ch), gname[ch])

    glyph_order = {n: i for i, n in enumerate(font.getGlyphOrder())}
    hide = gsub_mod.build_single_subst_lookup(
        {gname[ch]: blank for ch in sorted(chars)}, extension=True)

    subtables = []
    for _, text, _ in cases:
        st = ot.ChainContextSubst()
        st.Format = 3
        st.BacktrackGlyphCount = 0; st.BacktrackCoverage = []
        st.LookAheadGlyphCount = 0; st.LookAheadCoverage = []
        st.InputCoverage = [gsub_mod._coverage([gname[c]], glyph_order) for c in text]
        st.InputGlyphCount = len(st.InputCoverage)
        rec = ot.SubstLookupRecord(); rec.SequenceIndex = 0; rec.LookupListIndex = 0
        st.SubstLookupRecord = [rec]; st.SubstCount = 1
        subtables.append(st)
    # longest first, so 月｜ラ does not lose to a shorter prefix rule
    subtables.sort(key=lambda s: -s.InputGlyphCount)

    lk = ot.Lookup(); lk.LookupType = 7; lk.LookupFlag = 0
    lk.SubTable = [gsub_mod._extend(s, 6) for s in subtables]
    lk.SubTableCount = len(lk.SubTable)

    gsub = gsub_mod.build_gsub([hide, lk], [("ccmp", [1])])
    tbl = newTable("GSUB"); tbl.table = gsub
    font["GSUB"] = tbl
    for t in ("GPOS", "GDEF"):
        if t in font:
            del font[t]
    for nid, val in ((1, "ItemizeProbe"), (4, "ItemizeProbe"), (6, "ItemizeProbe")):
        font["name"].setName(val, nid, 3, 1, 0x409)
    font["post"].formatType = 2.0
    font["post"].glyphOrder = font.getGlyphOrder()
    font["post"].extraNames = []; font["post"].mapping = {}
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    font.save(out)

    meta = [{"label": lbl, "text": txt, "note": note,
             "codepoints": [f"U+{ord(c):04X}" for c in txt]}
            for lbl, txt, note in cases]
    json.dump(meta, open(os.path.join(HERE, "itemize_cases.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"wrote {out}: {len(cases)} cases, {font['maxp'].numGlyphs} glyphs")
    print(f"wrote {os.path.join(HERE, 'itemize_cases.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
