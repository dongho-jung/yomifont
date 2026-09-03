# Licensing and attribution

YomiFont combines four externally licensed inputs. Two of them end up inside
the distributed font and carry obligations; two are build-time tools and do not.

| input | license | in the font? | obligation |
|---|---|---|---|
| JMdict | CC BY-SA 4.0 | **yes** (readings) | attribution + ShareAlike |
| Noto Sans JP | SIL OFL 1.1 | **yes** (outlines) | Reserved Font Name, no sale alone |
| UniDic (unidic-lite) | BSD / LGPL / GPL tri-license | no | none |
| Tatoeba sentences | CC BY 2.0 FR | no | none |
| YomiFont's own code | MIT | n/a | — |

---

## JMdict — CC BY-SA 4.0

Copyright © Electronic Dictionary Research and Development Group, Monash
University. Distributed under a
[Creative Commons Attribution-ShareAlike 4.0 licence](https://www.edrdg.org/edrdg/licence.html).

The reading data compiled into YomiFont's GSUB is derived from JMdict, so the
font is a derivative work and **ShareAlike applies to it**.

EDRDG's stated conditions require that users:

> acknowledge the usage and source of the files in the documentation, publicity
> material, WWW site of the package/server, etc.

and provide links to the documentation and licence files. For a web display,
"the acknowledgement must be made on each screen display".

What this repository does to comply:

- The font's `name` table carries the attribution in the Description record
  (ID 10) and the project URL in the Vendor URL record (ID 11):
  > YomiFont. Readings from JMdict (CC BY-SA 4.0, EDRDG). Outlines from Noto
  > Sans JP (SIL OFL 1.1).
- This file and the README state the source and licence.
- The recommended reference URL is
  <https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project>.

**If you redistribute the font**, you must keep that attribution, link to the
JMdict project, and license the font under CC BY-SA 4.0 or a compatible
licence. EDRDG places no restriction on commercial use provided the conditions
are met.

Note the composite obligation: the outlines are OFL and the reading data is
CC BY-SA. Both must be honoured simultaneously. That is why the distributed
artefact is licensed as CC BY-SA 4.0 *and* carries the OFL notice.

## Noto Sans JP — SIL Open Font License 1.1

Copyright © The Noto Project Authors. Retrieved from
`google/fonts/ofl/notosansjp/`; the licence text is kept verbatim at
`data/raw/OFL-notosansjp.txt`.

Three OFL clauses matter here:

1. **Reserved Font Name.** The OFL for Noto reserves "Noto". A modified version
   may not be distributed under that name. This is why the family is
   **YomiFont**, with no "Noto" anywhere in the `name` table.
2. **Modification is permitted**, including deriving new glyphs — YomiFont's
   ruby glyphs are composites referencing Noto's kana outlines, which is
   squarely within "Modified Versions".
3. **The font may not be sold by itself**, and any derivative must remain under
   the OFL. Bundling it in a larger work is fine.

The OFL and CC BY-SA are not the same licence, but they are not in conflict
here: OFL governs the outlines, CC BY-SA governs the reading data, and both
permit redistribution with attribution.

## UniDic / unidic-lite — build-time only

[unidic-lite](https://github.com/polm/unidic-lite) packages UniDic 2.1.2, which
is tri-licensed BSD / LGPL / GPL by the National Institute for Japanese
Language and Linguistics. It is used through
[fugashi](https://github.com/polm/fugashi) (MIT) over MeCab (BSD/LGPL/GPL).

UniDic is used for two things, both at build time:

- as an **evaluation oracle** (`scripts/evaluate.py`), and
- to derive **frequency priors** (`scripts/build_priors.py`).

The priors are *counts over (surface, reading) pairs that JMdict already
contains*. No UniDic reading, lemma, or dictionary entry is copied into the
font, and a pair JMdict does not have can never appear in the output. The
`--no-priors` build path removes the dependency entirely and produces a working
font (91.18 % vs 92.44 % correct tokens; see
[compatibility.md](compatibility.md)).

Because none of it is redistributed, UniDic's licence imposes no obligation on
the font. It is documented here anyway so the provenance of every number in
this repo is traceable.

## Tatoeba — CC BY 2.0 FR

Japanese sentences from <https://tatoeba.org>, licensed
[CC BY 2.0 FR](https://creativecommons.org/licenses/by/2.0/fr/). Used as the
evaluation and prior-training corpus. Not redistributed here (the build
downloads it) and not embedded in the font.

## YomiFont's own code — MIT

Everything under `src/`, `scripts/`, `tests/`, `benchmarks/` and `tools/` is
MIT licensed; see `LICENSE`.

## Summary for redistributors

If you ship `dist/YomiFont-Regular.ttf`:

- keep the `name` table attribution intact;
- state that readings come from JMdict (EDRDG, CC BY-SA 4.0) and link to the
  JMdict project page;
- state that outlines come from Noto Sans JP under the SIL OFL 1.1, and include
  `data/raw/OFL-notosansjp.txt`;
- license the font itself under CC BY-SA 4.0;
- do not rename it to anything containing "Noto";
- do not sell the font on its own.
