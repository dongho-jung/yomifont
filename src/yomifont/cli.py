"""Console entry point: `yomifont-build` == `scripts/pipeline.py`."""
from __future__ import annotations

import os
import runpy
import sys


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", ".."))
    script = os.path.join(root, "scripts", "pipeline.py")
    if not os.path.exists(script):
        print("pipeline.py not found; run from a source checkout", file=sys.stderr)
        return 1
    sys.path.insert(0, os.path.join(root, "scripts"))
    runpy.run_path(script, run_name="__main__")
    return 0
