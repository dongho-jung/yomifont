#!/usr/bin/env python3
"""Static file server for the browser compatibility harness, plus a /report
endpoint that browsers POST their results to.

    ./tests/integration/server.py [--port 8777]

Results land in tests/integration/reports/<engine>.json so Safari and Firefox
can be measured without a screenshot in the loop.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REPORTS = os.path.join(ROOT, "tests", "integration", "reports")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, fmt, *args):  # quieter
        if "/report" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def do_POST(self):
        if self.path != "/report":
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n) or b"{}")
        os.makedirs(REPORTS, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", payload.get("engine", "unknown"))[:60]
        path = os.path.join(REPORTS, f"{name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        print(f"[report] wrote {path}")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"serving {ROOT} on http://127.0.0.1:{args.port}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
