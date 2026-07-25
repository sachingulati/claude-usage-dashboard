"""Run the dashboard locally and keep it fresh.

- Builds the dashboard once, then serves output/ on 127.0.0.1:<port>.
- A background thread rebuilds every <refresh_minutes>; the open page reloads
  itself on the same interval, so a bookmarked tab stays current.
- Bound to localhost only. Runs happily under pythonw.exe (no console) for
  auto-start; all output goes to output/serve.log.

Usage:  python serve.py         (foreground, with console logging)
        pythonw serve.py        (background, log file only)
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import limits
from build import OUT_DIR, build
from dashboard_config import HERE, load_config

LOG = HERE / "output" / "serve.log"


def setup_logging() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler()],
    )


class Handler(SimpleHTTPRequestHandler):
    """Serve output/, sending the dashboard for the root path."""

    def do_GET(self):
        if self.path.startswith("/favicon.ico"):
            self.send_response(204)  # no favicon on the served page; skip the 404
            self.end_headers()
            return
        if self.path.split("?")[0] == "/limits.json":
            body = json.dumps(limits.get(load_config(), OUT_DIR)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path in ("/", "/index.html"):
            self.path = "/dashboard.html"
        return super().do_GET()

    def log_message(self, *args):
        pass  # keep the access log out of serve.log; we log our own events


def refresh_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        cfg = load_config()  # re-read so an edited interval takes effect
        # sleep in short slices so a stop request is responsive
        for _ in range(cfg["refresh_minutes"] * 60):
            if stop.wait(1):
                return
        try:
            build(cfg)
            logging.info("rebuilt dashboard")
        except Exception as exc:  # never let a transient failure kill the loop
            logging.error("rebuild failed: %s", exc)


def main() -> None:
    setup_logging()
    cfg = load_config()
    logging.info("starting; refresh every %s min, port %s", cfg["refresh_minutes"], cfg["port"])

    try:
        build(cfg)
        logging.info("initial build ok")
    except Exception as exc:
        logging.error("initial build failed: %s", exc)

    stop = threading.Event()
    threading.Thread(target=refresh_loop, args=(stop,), daemon=True).start()

    handler = partial(Handler, directory=str(OUT_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", int(cfg["port"])), handler)
    url = f"http://127.0.0.1:{cfg['port']}/"
    logging.info("serving at %s", url)
    # config decides, but --no-browser (used by the logon auto-start) always wins
    if cfg.get("open_browser") and "--no-browser" not in sys.argv:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("shutting down")
    finally:
        stop.set()
        server.shutdown()


if __name__ == "__main__":
    main()
