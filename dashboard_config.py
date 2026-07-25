"""Load config.toml with sensible defaults. Stdlib only (tomllib, Python 3.11+)."""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.toml"
# Machine-specific overrides live here and are gitignored, so the committed
# config stays portable.
LOCAL_CONFIG_PATH = HERE / "config.local.toml"

DEFAULTS = {
    "refresh_minutes": 60,
    "port": 8787,
    "open_browser": True,
    "tz_offset_hours": 5.5,
    "tz_label": "Asia/Kolkata (UTC+5:30)",
    "transcripts_dir": "",
    "accounts": [],
}


def load_config() -> dict:
    """Defaults <- config.toml <- config.local.toml. Missing files are fine."""
    cfg = dict(DEFAULTS)
    for path in (CONFIG_PATH, LOCAL_CONFIG_PATH):
        if path.exists():
            with open(path, "rb") as fh:
                cfg.update(tomllib.load(fh))
    # clamp refresh to something sane; 0/negative would busy-loop the server
    cfg["refresh_minutes"] = max(1, int(cfg["refresh_minutes"]))
    return cfg


def _expand(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(p))))


def transcript_roots(cfg: dict) -> list[tuple[str, Path]]:
    """(account-label, transcripts-dir) pairs to read, in config order.

    Two supported layouts, and the difference matters:

    * One config directory shared by every login (accounts differ only by stored
      credential). Every account writes into the same `projects/` folder with no
      per-account marker, so there is exactly one root and usage is unavoidably
      combined -- the label comes back empty to say so.
    * A config directory per login (`CLAUDE_CONFIG_DIR` per account). Each has
      its own `projects/` folder, so the folder a transcript came from *is* the
      account, and usage can be attributed.

    An explicit `transcripts_dir` always wins; give it a list to read several
    roots. A bare string stays a single unattributed root, as before.
    """
    td = cfg.get("transcripts_dir")
    if isinstance(td, (list, tuple)):
        out = [(_expand(p).parent.name, _expand(p)) for p in td if str(p).strip()]
        return [(lbl, d) for lbl, d in out if d.is_dir()]
    if td and str(td).strip():
        return [("", _expand(td))]

    # derive from the configured accounts: each account's own projects/ folder
    pairs: list[tuple[str, Path]] = []
    for a in cfg.get("accounts") or []:
        label = str(a.get("label") or "")
        raw = a.get("transcripts") or (Path(str(a.get("dir") or "~/.claude")) / "projects")
        pairs.append((label, _expand(raw)))
    pairs = [(lbl, d) for lbl, d in pairs if d.is_dir()]

    # Same folder behind several accounts is the shared-config layout: collapse
    # to one root and drop the labels, because the data cannot be split.
    distinct = {d.resolve() for _, d in pairs}
    if len(distinct) < len(pairs):
        return [("", sorted(distinct)[0])]
    if pairs:
        return pairs
    return [("", Path.home() / ".claude" / "projects")]


def home_slug() -> str:
    """This machine's home directory in Claude's transcript-folder encoding.

    Claude names a project's transcript folder after its cwd with every path
    separator and drive colon turned into '-', so C:\\Users\\Ada becomes
    C--Users-Ada. Recreating that for the home directory lets the dashboard
    shorten a folder name back to ~/... on whatever machine it runs on,
    instead of hardcoding one user's paths.
    """
    return re.sub(r"[\\/:]", "-", str(Path.home()))


def emit_env(cfg: dict) -> dict:
    """Environment for emit_cube.py, derived from config."""
    env = dict(os.environ)
    env["CLAUDE_USAGE_TZ_OFFSET"] = str(cfg["tz_offset_hours"])
    env["CLAUDE_USAGE_TZ_LABEL"] = str(cfg["tz_label"])
    env["CLAUDE_USAGE_OUT"] = str(HERE / "output" / "cube.json")
    roots = transcript_roots(cfg)
    env["CLAUDE_USAGE_ROOTS"] = json.dumps([[lbl, str(d)] for lbl, d in roots])
    # kept for anything invoking emit_cube.py directly with the old contract
    if len(roots) == 1:
        env["CLAUDE_USAGE_ROOT"] = str(roots[0][1])
    return env
