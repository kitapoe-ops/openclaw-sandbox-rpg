"""
Phase D4 v2 — E-Blocker resolution tests
=========================================

This test file is the regression net for the four E-blockers the
M3-as-R1 audit flagged in ``docs/AUDIT_D4_M3.json`` (Phase D4 ship
verdict = CONDITIONAL). Each test pins down the fix so that any
re-introduction of the issue is caught immediately.

E-Blockers and the corresponding test:

    1. HTTP action is echo-only          → test_http_action_marked_echo_in_frontend
    2. No list-characters endpoint       → test_list_characters_endpoint_works
    3. CORS allowlist too narrow         → test_serve_demo_script_binds_port
                                          → test_serve_demo_script_serves_html
    4. Polling fallback is log noise     → test_polling_fallback_removed
    (XSS safety is re-checked by)        → test_xss_safe_after_changes

The tests are deliberately file-based and behavioural (not mock-heavy):
the frontend is a static file, so we read its source and assert on
specific strings. The new list-characters endpoint is exercised via
``httpx.AsyncClient`` + ``ASGITransport`` against the *real* composed
app, exactly the same way the browser would call it.
"""
from __future__ import annotations

import asyncio
import os
import socket
import sys
import time
from pathlib import Path
from typing import AsyncIterator, Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Ensure repo root on sys.path so ``backend.*`` imports resolve.
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Local imports — ``app_with_memory`` is the composed app (frozen
# ``main`` + the new D4 v2 list-characters router).
from backend.app_with_memory import app as composed_app  # noqa: E402

# ============================================
# Path constants
# ============================================
REPO_ROOT = Path(_REPO_ROOT)
DEMO_HTML = REPO_ROOT / "demo.html"
SERVE_DEMO_SCRIPT = REPO_ROOT / "backend" / "scripts" / "serve_demo.py"


# ============================================
# Test 1 — E-Blocker 1: HTTP action is echo-only
# ============================================
class TestHTTPECHOUI:
    """The HTTP path is a debug echo. The UI must make this clear."""

    def test_http_action_marked_echo_in_frontend(self) -> None:
        """demo.html must contain an explicit "ECHO ONLY" warning.

        The brief asks for an orange badge + tooltip explaining that
        the HTTP path is debug-only. We assert on the *string* in the
        source — this catches both the badge removal AND the
        regression where someone reverts the "ECHO" wording to
        "SUBMITTED".
        """
        assert DEMO_HTML.exists(), f"{DEMO_HTML} missing"
        src = DEMO_HTML.read_text(encoding="utf-8")
        # The badge text — must be present at least once.
        assert "HTTP ECHO ONLY" in src, (
            "demo.html no longer has the 'HTTP ECHO ONLY' badge — "
            "E-Blocker 1 (HTTP echo is a no-op) has been reintroduced."
        )
        # The tooltip text — must be present at least once.
        assert (
            "HTTP echo is a debug feature" in src
        ), "demo.html is missing the 'HTTP echo is a debug feature' tooltip."

    def test_frontend_uses_dedicated_echo_history_status(self) -> None:
        """History entries for HTTP echo should be 'HTTP_ECHO', not 'SUBMITTED'.

        This makes the log filterable (e.g. ``grep HTTP_ECHO``) and
        signals to power users that the action was a no-op.
        """
        src = DEMO_HTML.read_text(encoding="utf-8")
        assert "'HTTP_ECHO'" in src or '"HTTP_ECHO"' in src, (
            "demo.html is not using a dedicated 'HTTP_ECHO' history status."
        )


# ============================================
# Test 2 — E-Blocker 2: list-characters endpoint
# ============================================
@pytest_asyncio.fixture
async def list_endpoint_client() -> AsyncIterator[AsyncClient]:
    """Async client bound to the composed app (no DB fixture needed).

    The new /api/character-list/ endpoint works in demo mode without
    any Postgres/Vector store, so we don't need the heavier fixture
    used in test_d4_frontend_e2e.py. We just bind to the real app.
    """
    transport = ASGITransport(app=composed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestListCharactersEndpoint:
    """GET /api/character-list/ returns the available characters."""

    @pytest.mark.asyncio
    async def test_list_characters_endpoint_works(
        self, list_endpoint_client: AsyncClient,
    ) -> None:
        """The endpoint exists, returns 200, and returns a list of
        dicts with the contract the frontend picker expects.
        """
        # 1. Route is registered on the composed app.
        paths = sorted(
            r.path for r in composed_app.routes if hasattr(r, "path")
        )
        assert "/api/character-list/" in paths, (
            f"/api/character-list/ is not a route on the composed app. "
            f"Available /api/* paths: {[p for p in paths if p.startswith('/api')]!r}"
        )

        # 2. Endpoint responds 200.
        resp = await list_endpoint_client.get("/api/character-list/")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # 3. Response is a non-empty list.
        assert isinstance(body, list), f"Expected list, got {type(body)}"
        assert len(body) >= 1, f"Expected at least 1 character, got {body!r}"

        # 4. Each entry has the picker contract.
        for entry in body:
            for required in (
                "character_id", "name", "world_id", "current_scene_id",
                "is_alive", "is_npc_mode", "source",
            ):
                assert required in entry, (
                    f"Character entry missing {required!r}: {entry!r}"
                )

        # 5. The hardcoded demo starter is present.
        ids = {e["character_id"] for e in body}
        assert "char_demo_player" in ids, (
            f"Demo starter 'char_demo_player' missing from list: {ids!r}"
        )

    @pytest.mark.asyncio
    async def test_list_characters_includes_demo_starter_with_source(
        self, list_endpoint_client: AsyncClient,
    ) -> None:
        """Specifically assert the demo starter is tagged with source='demo'.

        The frontend renders the source in the picker dropdown label
        (e.g. "Aelar (demo)"). If a future change renames or drops
        this field, the picker breaks.
        """
        resp = await list_endpoint_client.get("/api/character-list/")
        assert resp.status_code == 200
        body = resp.json()
        demo_entries = [e for e in body if e["source"] in ("demo", "demo-fallback")]
        assert demo_entries, f"No demo-sourced entries in {body!r}"
        assert demo_entries[0]["source"] == "demo", (
            f"Expected source='demo' (in demo mode), got {demo_entries[0]['source']!r}"
        )


# ============================================
# Test 3 — E-Blocker 3: CORS allowlist (serve_demo.py)
# ============================================
def _is_port_free(host: str, port: int) -> bool:
    """Return True if ``(host, port)`` is not currently bound.

    Used to pick an alternative port for the smoke test when 5173
    happens to be taken (e.g. by a long-running dev server). The
    standard library ``socket.connect_ex`` returns 0 on success.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        return s.connect_ex((host, port)) != 0
    finally:
        s.close()


def _find_free_port(preferred: int = 5173) -> int:
    """Return ``preferred`` if free, else scan for the next free one."""
    if _is_port_free("127.0.0.1", preferred):
        return preferred
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestServeDemoScript:
    """Verify the static-file server (CORS fix) actually works."""

    def test_serve_demo_script_binds_port(self) -> None:
        """The script imports cleanly and exposes a TCPServer bound to 5173.

        We start it in a background thread on whatever port is free
        (5173 in CI; some other port in dev), then assert the
        listener is reachable. This is the same smoke test the brief
        asks for, with one extra safety: we don't fail if 5173 is in
        use — we just pick another port and adapt the assertion.
        """
        assert SERVE_DEMO_SCRIPT.exists(), (
            f"{SERVE_DEMO_SCRIPT} missing — Step 3 (CORS) not implemented."
        )

        # The script must be importable so we can re-use its handler.
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        try:
            from scripts.serve_demo import DemoHandler  # type: ignore
        except ImportError as exc:  # pragma: no cover — safety net
            pytest.fail(f"scripts.serve_demo.DemoHandler not importable: {exc}")

        import threading
        import socketserver

        port = _find_free_port(5173)
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("127.0.0.1", port), DemoHandler) as httpd:
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                # Give the OS a moment to register the socket.
                time.sleep(0.1)
                # Connect a raw socket — confirms the bind actually
                # worked, without doing a full HTTP roundtrip here
                # (that's the next test).
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.0)
                try:
                    rc = s.connect_ex(("127.0.0.1", port))
                    assert rc == 0, (
                        f"connect_ex to 127.0.0.1:{port} returned {rc} "
                        f"— server failed to accept connections"
                    )
                finally:
                    s.close()
            finally:
                httpd.shutdown()
                httpd.server_close()
                t.join(timeout=2.0)

    def test_serve_demo_script_serves_html(self) -> None:
        """A GET /demo.html against the running server returns 200 + HTML.

        This is the full roundtrip the CORS fix enables: a browser
        hitting http://localhost:5173/demo.html gets the page back
        with the ``Access-Control-Allow-Origin: *`` header.
        """
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        from scripts.serve_demo import DemoHandler  # type: ignore

        import threading
        import socketserver
        import urllib.request

        port = _find_free_port(5173)
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("127.0.0.1", port), DemoHandler) as httpd:
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                time.sleep(0.1)
                url = f"http://127.0.0.1:{port}/demo.html"
                with urllib.request.urlopen(url, timeout=2.0) as resp:
                    assert resp.status == 200, (
                        f"GET {url} returned {resp.status}"
                    )
                    body = resp.read().decode("utf-8", errors="replace")
                    # Sanity-check: the served file is actually our
                    # demo.html (look for the unique title).
                    assert "OpenClaw Sandbox RPG" in body, (
                        "Served /demo.html body does not contain the "
                        "expected title — wrong file being served?"
                    )
                    # CORS header must be present on the response.
                    acao = resp.headers.get("Access-Control-Allow-Origin")
                    assert acao == "*", (
                        f"Missing/wrong Access-Control-Allow-Origin: {acao!r}"
                    )
            finally:
                httpd.shutdown()
                httpd.server_close()
                t.join(timeout=2.0)


# ============================================
# Test 4 — E-Blocker 4: polling fallback removed
# ============================================
class TestPollingFallbackRemoved:
    """``setInterval`` is gone; WS retry + manual reconnect are the path."""

    def test_polling_fallback_removed(self) -> None:
        """demo.html does not poll the *single-player* ``loadScene`` flow.

        E-Blocker 4 was specifically about a 5-second ``setInterval``
        that re-fetched the scene in single-player demo mode, which
        produced pure log noise because the scene never changes between
        calls. The fix in D4 v2 was to drop *that* interval.

        Phase E6c (multiplayer frontend) legitimately re-introduced a
        ``setInterval`` for ``mpRefreshRoster`` so the slot list stays
        honest when a player joins from another tab and no WebSocket
        push arrives. That is a *cross-tab sync* concern, not the same
        log-noise problem.

        Scope of this test: scan for ``setInterval(loadScene`` (or any
        call that targets the single-player scene-refresh pipeline).
        The multiplayer roster refresh is permitted.
        """
        import re

        src = DEMO_HTML.read_text(encoding="utf-8")
        # Strip // and /* */ comments to ignore explanatory notes.
        no_block_comments = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
        no_line_comments = re.sub(r"//[^\n]*", "", no_block_comments)

        # Disallow the original single-player polling targets.
        forbidden_patterns = [
            r"setInterval\s*\(\s*loadScene",
            r"setInterval\s*\(\s*getCurrentScene",
        ]
        for pattern in forbidden_patterns:
            match = re.search(pattern, no_line_comments)
            assert match is None, (
                f"demo.html still polls the single-player scene pipeline "
                f"({pattern!r}) — E-Blocker 4 (polling log noise) has been "
                f"reintroduced. The multiplayer roster refresh interval is "
                f"permitted because it serves cross-tab sync."
            )

    def test_manual_reconnect_button_is_exposed(self) -> None:
        """A user-visible reconnect button is wired to ``manualReconnect``.

        This catches a regression where someone removes the polling
        fallback but forgets to add the manual recovery surface.
        """
        src = DEMO_HTML.read_text(encoding="utf-8")
        assert "manualReconnect" in src, (
            "demo.html no longer exposes a manualReconnect function — "
            "users have no way to recover from a WS failure."
        )
        # The Vue template must actually call it from a button:
        assert "@click=\"manualReconnect\"" in src, (
            "demo.html has manualReconnect defined but no @click binding."
        )


# ============================================
# Test 5 — XSS safety re-check after all changes
# ============================================
class TestXSSSafeAfterChanges:
    """XSS invariants must be preserved through D4 v2."""

    def test_xss_safe_after_changes(self) -> None:
        """No ``v-html``, ``innerHTML``, ``outerHTML``, or ``document.write``
        calls in the live code of ``demo.html``.
        """
        import re

        src = DEMO_HTML.read_text(encoding="utf-8")
        # Strip comments so the audit-style "XSS-safe" notes don't
        # trigger false positives.
        no_block_comments = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
        no_line_comments = re.sub(r"//[^\n]*", "", no_block_comments)
        # Also strip <!-- ... --> HTML comments.
        no_html_comments = re.sub(
            r"<!--.*?-->", "", no_line_comments, flags=re.DOTALL
        )
        for token in ("v-html", "innerHTML", "outerHTML", "document.write"):
            assert token not in no_html_comments, (
                f"demo.html contains forbidden XSS vector: {token!r}"
            )
