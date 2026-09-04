PY      ?= .venv/bin/python
PYPATH   = PYTHONPATH=src
DIST     = dist/YomiFont-Regular.ttf
WEB      = dist/YomiFont-Web-Regular.ttf
EVAL_N  ?= 20000
TRAIN   ?= 20000:150000

.PHONY: help venv data font web all test eval eval-blink visual names audit bench \
        bench-explicit tools serve clean distclean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

venv: ## create the virtualenv and install dependencies
	uv venv --python 3.13 .venv
	uv pip install --python $(PY) fonttools uharfbuzz brotli zopfli pytest \
	    fugashi unidic-lite opentype-sanitizer

data: data/raw/JMdict_e.gz data/raw/JMnedict.xml.gz data/raw/NotoSansJP-Regular.ttf data/raw/NotoSansJP-w500.ttf data/raw/jpn_sentences.tsv ## fetch all inputs

data/raw/JMnedict.xml.gz:
	mkdir -p data/raw
	curl -sSL -o $@ http://ftp.edrdg.org/pub/Nihongo/JMnedict.xml.gz

data/raw/NotoSansJP-w500.ttf: data/raw/NotoSansJP-VF.ttf   ## heavier instance used for ruby outlines
	$(PY) -c "from fontTools.ttLib import TTFont; \
	from fontTools.varLib.instancer import instantiateVariableFont as I; \
	f=TTFont('$<'); I(f, {'wght':500}, inplace=True); f.save('$@')"

data/raw/JMdict_e.gz:
	mkdir -p data/raw
	curl -sSL -o $@ http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz

data/raw/NotoSansJP-VF.ttf:
	mkdir -p data/raw
	curl -sSL -o $@ 'https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf'
	curl -sSL -o data/raw/OFL-notosansjp.txt \
	    https://raw.githubusercontent.com/google/fonts/main/ofl/notosansjp/OFL.txt

data/raw/NotoSansJP-Regular.ttf: data/raw/NotoSansJP-VF.ttf
	$(PY) -c "from fontTools.ttLib import TTFont; \
	from fontTools.varLib.instancer import instantiateVariableFont as I; \
	f=TTFont('$<'); I(f, {'wght':400}, inplace=True); f.save('$@')"

data/raw/jpn_sentences.tsv:
	mkdir -p data/raw
	curl -sSL -o $@.bz2 https://downloads.tatoeba.org/exports/per_language/jpn/jpn_sentences.tsv.bz2
	bunzip2 -kf $@.bz2

data/normalized/lexicon.jsonl: data/raw/JMdict_e.gz
	$(PYPATH) $(PY) -m yomifont.jmdict $< $@

data/normalized/names.jsonl: data/raw/JMnedict.xml.gz
	$(PYPATH) $(PY) -m yomifont.jmnedict $< $@

font: data ## build dist/YomiFont-Regular.ttf
	$(PYPATH) $(PY) scripts/pipeline.py --out $(DIST) --stats-out dist/build-stats.json

web: ## build the smaller 60k-rule web font
	$(PYPATH) $(PY) scripts/pipeline.py --limit 60000 --out $(WEB) --family "YomiFont Web" \
	    --no-explicit-bases

all: font web ## build both fonts

tools: ## build the CoreText shaping harness (macOS)
	swiftc -O -o tools/ctshape/ctshape tools/ctshape/main.swift

test: ## shaping tests (HarfBuzz + CoreText)
	$(PYPATH) $(PY) -m pytest tests/ -q

eval: ## precision / coverage vs UniDic, non-segmenting engines
	$(PYPATH) $(PY) scripts/evaluate.py --limit $(EVAL_N)

eval-blink: ## same, modelling Blink script segmentation
	$(PYPATH) $(PY) scripts/evaluate.py --limit $(EVAL_N) --segmentation script \
	    --report data/normalized/eval_blink.json

visual: ## typography contact sheet + geometric metrics
	PYTHONPATH=src:tests/shaping $(PY) tests/visual/specimens.py

names: ## experimental build with ALL JMnedict names (does NOT compile, see docs)
	$(PYPATH) $(PY) scripts/pipeline.py --names all --out dist/YomiFont-Names.ttf \
	    --family "YomiFont Names" --rules data/normalized/rules_names.jsonl

audit: ## does every rule spell the reading it came from?
	$(PYPATH) $(PY) scripts/audit_readings.py

bench: ## scaling benchmark, 1k -> all rules
	$(PYPATH) $(PY) benchmarks/scale.py --sizes 1000,5000,10000,25000,50000,100000,200000,300000,0

bench-explicit: ## explicit ruby scales by span length, not vocabulary
	$(PYPATH) $(PY) benchmarks/explicit_scale.py

serve: ## serve the repo for the browser compatibility harness
	$(PY) tests/integration/server.py

clean:
	command rm -rf build/*.ttf build/*.png benchmarks/bench_*.ttf

distclean: clean
	command rm -rf dist/*.ttf data/normalized/*
