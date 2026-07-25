"""Live 5-hour / weekly quota for one or more Claude logins.

Self-contained: reads each account's own `.credentials.json` and calls the same
read-only endpoint the `/usage` command uses. Nothing outside this project is
required, and no account paths are hard-coded -- they come from config, with the
default login auto-detected so it works on a fresh machine out of the box.

The token is read only to authorise this one request. It is never logged, never
written anywhere, and goes only to api.anthropic.com over HTTPS. Per Anthropic's
docs this endpoint is a plain read: it does not consume model quota.

Results are cached in output/limits-cache.json with a per-account backoff, and
refreshed on a background thread so a slow network never blocks a page load.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

OK_INTERVAL = 1800    # normal cadence
IDLE_INTERVAL = 3600  # account sitting at exactly 0% -- nothing to watch
ERR_INTERVAL = 240    # retry sooner after a transient failure
TIMEOUT = 10

_inflight: set[str] = set()
_lock = threading.Lock()


def accounts(cfg: dict) -> list[tuple[str, Path]]:
    """(label, credentials-dir) pairs that actually have a login on this machine.

    Configured accounts win; with none configured we fall back to the standard
    location, so a stock install shows its own quota with no setup.
    """
    listed = cfg.get("accounts") or []
    out: list[tuple[str, Path]] = []
    for a in listed:
        raw = str(a.get("dir") or "~/.claude")
        d = Path(os.path.expandvars(os.path.expanduser(raw)))
        out.append((str(a.get("label") or d.name), d))
    if not out:
        out.append(("default", Path.home() / ".claude"))
    return [(label, d) for label, d in out if (d / ".credentials.json").is_file()]


def _cache_file(out_dir: Path) -> Path:
    return out_dir / "limits-cache.json"


def _read_cache(out_dir: Path) -> dict:
    try:
        return json.loads(_cache_file(out_dir).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_entry(out_dir: Path, label: str, entry: dict) -> None:
    with _lock:
        cache = _read_cache(out_dir)
        cache[label] = entry
        tmp = _cache_file(out_dir).with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(cache), encoding="utf-8")
            tmp.replace(_cache_file(out_dir))
        except Exception:
            tmp.unlink(missing_ok=True)


def _epoch(iso) -> int | None:
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def _window(o) -> dict | None:
    if not o:
        return None
    return {"utilization": o.get("utilization"), "resets_at": _epoch(o.get("resets_at"))}


def _fetch(creds_dir: Path):
    """-> (status, data|None, seconds-until-next-attempt)."""
    try:
        raw = json.loads((creds_dir / ".credentials.json").read_text(encoding="utf-8"))
        token = (raw.get("claudeAiOauth") or {}).get("accessToken")
    except Exception:
        return "nocreds", None, ERR_INTERVAL
    if not token:
        return "nocreds", None, ERR_INTERVAL

    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": "Bearer " + token,
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "claude-usage-dashboard",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Deliberately no token refresh here: rotating it rewrites
        # .credentials.json, which a live session for that account owns.
        if e.code in (401, 403):
            return "auth", None, ERR_INTERVAL
        if e.code == 429:
            return "ratelimited", None, OK_INTERVAL
        return "error", None, ERR_INTERVAL
    except Exception:
        return "error", None, ERR_INTERVAL

    data = {"five_hour": _window(payload.get("five_hour")),
            "seven_day": _window(payload.get("seven_day"))}
    five = data["five_hour"] or {}
    # Exactly 0% means idle -- nothing is consuming the window, so back well off.
    idle = five.get("utilization") == 0
    return "ok", data, (IDLE_INTERVAL if idle else OK_INTERVAL)


def _refresh(label: str, creds_dir: Path, out_dir: Path) -> None:
    try:
        status, data, nxt = _fetch(creds_dir)
        now = int(time.time())
        prev = _read_cache(out_dir).get(label) or {}
        _write_entry(out_dir, label, {
            "key": label,
            "status": status,
            # keep the last good numbers on failure; only the age grows
            "fetched_at": now if data else prev.get("fetched_at"),
            "checked_at": now,
            "next_attempt_at": now + nxt,
            "five_hour": data["five_hour"] if data else prev.get("five_hour"),
            "seven_day": data["seven_day"] if data else prev.get("seven_day"),
        })
    finally:
        with _lock:
            _inflight.discard(label)


def get(cfg: dict, out_dir: Path) -> dict:
    """Current quota for every configured account, refreshing what's due."""
    out_dir.mkdir(exist_ok=True)
    accts = accounts(cfg)
    cache = _read_cache(out_dir)
    now = int(time.time())

    for label, creds_dir in accts:
        entry = cache.get(label) or {}
        if entry.get("next_attempt_at", 0) > now:
            continue
        with _lock:
            if label in _inflight:
                continue
            _inflight.add(label)
        threading.Thread(target=_refresh, args=(label, creds_dir, out_dir),
                         daemon=True).start()

    return {"now": now, "accounts": [
        dict(cache.get(label) or {"status": "pending"}, key=label)
        for label, _ in accts]}
