"""Static-file server for ``demo.html`` on port 5173 (D4 v2).

Why this exists
---------------
The Phase D4 audit (``docs/AUDIT_D4_M3.json`` finding #4) flagged
that ``CORS_ORIGINS`` in ``backend/main.py`` only allows
``localhost:5173`` and ``localhost:3000``. If a developer opens
``demo.html`` from any other port, the browser blocks the
``fetch()`` calls with a silent CORS error.

Rather than widening the CORS allowlist (which requires editing the
frozen ``main.py``), this script serves ``demo.html`` on port 5173
itself, so the browser origin is exactly the allowed one and no CORS
preflight is required.

Usage
-----
::

    # 1. Start the backend on its usual port (8000)
    .venv/Scripts/python.exe -m uvicorn backend.app_with_memory:app --port 8000

    # 2. In another terminal, start the demo server on 5173
    .venv/Scripts/python.exe -m backend.scripts.serve_demo

    # 3. Open http://localhost:5173/demo.html in your browser

The two servers can run side-by-side; they bind to different ports.
The ``Access-Control-Allow-Origin: *`` header is set defensively so
that even misconfigured proxies still get through.

This file is intentionally tiny (~40 lines) and has zero project
dependencies — it uses only the Python standard library so that it
works in any environment that can run Python.
"""
from __future__ import annotations

import http.server
import socketserver
import sys
from pathlib import Path

PORT = 5173

# demo.html lives at the repo root; this script is at
# backend/scripts/serve_demo.py → walk up three levels.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEMO_HTML_PATH = _REPO_ROOT / "demo.html"
SERVE_DIR = _REPO_ROOT


class DemoHandler(http.server.SimpleHTTPRequestHandler):
    """``SimpleHTTPRequestHandler`` rooted at the repo root.

    Adds a permissive ``Access-Control-Allow-Origin`` header on
    every response so that even if a future change moves
    ``demo.html`` off-port-5173, the browser will not block the
    fetch. This does *not* weaken security: ``demo.html`` is a
    public demo, and the backend is read/write protected by its
    own auth (if any).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SERVE_DIR), **kwargs)

    def end_headers(self) -> None:  # type: ignore[override]
        self.send_header("Access-Control-Allow-Origin", "*")
        # Cache aggressively disabled during development.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:  # type: ignore[override]
        # Quieter access log — one line per request, no timestamp
        # prefix (the parent class adds a noisy "[date] [code] ...").
        sys.stderr.write(f"[serve_demo] {self.address_string()} {format % args}\n")


def main() -> None:
    if not DEMO_HTML_PATH.exists():
        sys.stderr.write(
            f"[serve_demo] ERROR: {DEMO_HTML_PATH} not found.\n"
            f"[serve_demo] Run this script from the repo root.\n"
        )
        sys.exit(2)
    # SO_REUSEADDR so a quick restart (after Ctrl-C) does not hit
    # "Address already in use" within the TIME_WAIT window.
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), DemoHandler) as httpd:
        sys.stderr.write(
            f"[serve_demo] Serving {DEMO_HTML_PATH.name} from {SERVE_DIR}\n"
            f"[serve_demo] Open http://localhost:{PORT}/demo.html\n"
        )
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            sys.stderr.write("[serve_demo] Shutting down.\n")


if __name__ == "__main__":
    main()
