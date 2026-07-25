"""Regenerate output/dashboard.html from fresh transcript data.

Runs emit_cube.py (writes output/cube.json), then injects that cube and the
refresh interval into dashboard.template.html to produce a self-contained
output/dashboard.html. Safe to run repeatedly; the server calls it on a timer.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from dashboard_config import HERE, emit_env, home_slug, load_config

TEMPLATE = HERE / "dashboard.template.html"
LOGIC = HERE / "dashboard.logic.js"
OUT_DIR = HERE / "output"
CUBE = OUT_DIR / "cube.json"
DASHBOARD = OUT_DIR / "dashboard.html"


def build(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    OUT_DIR.mkdir(exist_ok=True)

    # 1. regenerate the cube from the transcripts
    proc = subprocess.run(
        [sys.executable, str(HERE / "emit_cube.py")],
        env=emit_env(cfg), cwd=str(HERE),
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"emit_cube failed:\n{proc.stdout}\n{proc.stderr}")

    # 2. inject the cube + refresh interval into the template
    template = TEMPLATE.read_text(encoding="utf-8")
    cube_json = CUBE.read_text(encoding="utf-8")
    logic_js = LOGIC.read_text(encoding="utf-8")
    refresh_seconds = cfg["refresh_minutes"] * 60

    html = template.replace("/*__DATA__*/{}", cube_json, 1)
    html = html.replace("/*__REFRESH__*/0", str(refresh_seconds), 1)
    html = html.replace('/*__HOME__*/""', json.dumps(home_slug()), 1)
    html = html.replace("/*__LOGIC__*/", logic_js, 1)
    if any(p in html for p in ('/*__DATA__*/{}', '/*__REFRESH__*/0',
                               '/*__HOME__*/""', '/*__LOGIC__*/')):
        raise RuntimeError("template placeholder not substituted — check the template")

    # written pure-ASCII (template + JSON are both ASCII) so it renders under
    # any charset, whether opened as a file or served. Point at the offending
    # character instead of raising a bare UnicodeEncodeError from deep in the
    # write: in HTML use an entity, in JS a \\uXXXX escape.
    try:
        DASHBOARD.write_text(html, encoding="ascii", errors="strict")
    except UnicodeEncodeError as exc:
        line = html.count("\n", 0, exc.start) + 1
        char = html[exc.start]
        raise RuntimeError(
            f"non-ASCII character {char!r} (U+{ord(char):04X}) at line {line} "
            f"of the generated page -- the output must stay ASCII (no charset "
            f"is declared). Use an HTML entity or a \\u{ord(char):04x} escape "
            f"in dashboard.template.html.\n  ...{html[max(0, exc.start - 60):exc.start + 20]}..."
        ) from None
    return DASHBOARD


if __name__ == "__main__":
    t0 = time.time()
    path = build()
    size_kb = path.stat().st_size / 1024
    print(f"built {path}  ({size_kb:.0f} KB) in {time.time() - t0:.1f}s")
