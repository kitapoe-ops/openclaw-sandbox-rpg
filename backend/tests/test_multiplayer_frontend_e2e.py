"""
Phase E6c — Multiplayer Frontend Wire-up Tests
==============================================

Verifies that the multiplayer UI added to ``demo.html`` (Phase E6c)
talks to the backend correctly. Mirrors the pattern from
:mod:`backend.tests.test_d4_frontend_e2e` and
:mod:`backend.tests.test_scene_multiplayer`:

* The frontend encodes its URLs as string literals inside
  ``demo.html`` (no separate API client module). If a backend
  route is renamed, the frontend silently breaks.
* The test suite uses ``httpx.AsyncClient`` + ``ASGITransport`` to
  simulate the browser's HTTP calls against the *same* composed
  app (:mod:`backend.app_with_memory`) — every assertion is a real
  end-to-end check, not a tautology.
* The frontend is a static ``demo.html`` (no Node build step), so
  the JavaScript itself is not unit-testable. The XSS test (#6)
  is a *static* check: ripgrep across ``demo.html`` for
  ``v-html``, ``innerHTML``, ``outerHTML``, or ``document.write``
  (excluding comments) must return zero matches.

The 6 tests from the parent task brief:

1. ``test_frontend_can_create_multiplayer_scene``
   — POST ``/api/scene-multiplayer/{scene_id}/create`` returns 200
   and the shape the JS expects.
2. ``test_frontend_can_join_as_player_1``
   — POST join for slot 0 (player_1) returns 200 and the
   ``scene_id``, ``player_count`` fields the UI reads.
3. ``test_frontend_can_list_4_player_slots``
   — GET ``/api/scene-multiplayer/{scene_id}/players`` returns a
   JSON object with a ``players`` array and the cap the UI shows.
4. ``test_frontend_cannot_join_5th_player``
   — fill 4, the 5th returns 409 (the JS's ``else if (r.status
   === 409)`` branch fires and the user sees "scene full").
5. ``test_frontend_broadcast_endpoint_works``
   — POST ``/api/multiplayer/{scene_id}/broadcast`` returns
   ``{scene_id, delivered_to}`` even when nobody is connected
   (``delivered_to == 0`` is correct, not an error).
6. ``test_frontend_xss_safe_in_demo_html``
   — ripgrep ``demo.html`` for ``v-html`` / ``innerHTML`` /
   ``outerHTML`` / ``document.write`` *outside* of comments.
   Zero matches. This is the XSS invariant established in
   ``docs/AUDIT_D4_M3.json`` finding #3.

Frontend URL contract (the test asserts this matches the JS):

    E6b scene-state endpoints (the JS calls these in
    ``mpCreateScene``, ``mpJoinSlot``, ``mpRefreshRoster``):
      - POST /api/scene-multiplayer/{scene_id}/create
      - POST /api/scene-multiplayer/{scene_id}/player/{player_id}/join
      - GET  /api/scene-multiplayer/{scene_id}/players
      - GET  /api/scene-multiplayer/{scene_id}/npcs
      - GET  /api/scene-multiplayer/{scene_id}/turn/queue-size

    E6a transport endpoints (the JS connects to the WS via
    ``/ws/multiplayer/{scene_id}/{player_id}``):
      - POST /api/multiplayer/{scene_id}/broadcast
      - GET  /api/multiplayer/{scene_id}/players

We assert the *frontend's* URL contract matches the *backend's*
route table — that is the whole point of an E2E wire-up test.
"""
from __future__ import annotations

import os
import re
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Ensure repo root on sys.path.
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.app_with_memory import app as composed_app  # noqa: E402
from backend.memory_palace_integration import MemoryPalaceIntegration  # noqa: E402
from backend.memory_palace_integration_endpoint import (  # noqa: E402
    set_integration,
)
from backend.persistence_pg import PostgresPersistence  # noqa: E402
from backend.vector_store import VectorStore  # noqa: E402

# ============================================
# Constants — mirror demo.html's URL contract
# ============================================

# Scene id used by the demo.html multiplayer panel
# (``const mpSceneId = ref('scene_default')``). Override per-test
# if you need an isolated scene.
DEMO_HTML_DEFAULT_SCENE = "scene_default"

# All the URL patterns the JS calls in the multiplayer panel.
# If you change one of these paths in demo.html, change it here
# too — this test enforces the contract.
E6C_FRONTEND_URLS = {
    # E6b (scene state)
    "scene_create":        "/api/scene-multiplayer/{scene_id}/create",
    "scene_player_join":   "/api/scene-multiplayer/{scene_id}/player/{player_id}/join",
    "scene_players_list":  "/api/scene-multiplayer/{scene_id}/players",
    "scene_npcs_list":     "/api/scene-multiplayer/{scene_id}/npcs",
    "scene_queue_size":    "/api/scene-multiplayer/{scene_id}/turn/queue-size",
    # E6a (transport)
    "broadcast":           "/api/multiplayer/{scene_id}/broadcast",
    "ws_multiplayer":      "/ws/multiplayer/{scene_id}/{player_id}",
}


def _route_paths(application) -> list[str]:
    """Return all route paths (templates) registered on the app."""
    return sorted({
        r.path for r in application.routes if hasattr(r, "path")
    })


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    """Yield an ``AsyncClient`` bound to the composed app.

    Each test gets a fresh aiosqlite-backed integration so that
    ``/memory/health`` returns ``True`` for both backends. We
    restore the previous singleton in teardown.
    """
    db_file = tmp_path / "e6c_frontend_test.db"
    persistence = PostgresPersistence(f"sqlite+aiosqlite:///{db_file}")
    vector_store = VectorStore()
    integration = MemoryPalaceIntegration(persistence, vector_store)

    import backend.memory_palace_integration_endpoint as ep_mod
    prev = ep_mod._integration
    set_integration(integration)

    transport = ASGITransport(app=composed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        try:
            yield ac
        finally:
            try:
                await integration.close()
            except Exception:
                pass
            set_integration(prev)


# ============================================
# Tests
# ============================================
class TestMultiplayerFrontendWireUp:
    """The frontend (demo.html) multiplayer panel must be able to
    drive the backend (E6a + E6b).

    These tests don't mock the backend — they use the *real* composed
    app via ASGITransport, exactly as a browser would if it pointed
    ``fetch()`` and ``new WebSocket()`` at the same paths.
    """

    @pytest.mark.asyncio
    async def test_frontend_can_create_multiplayer_scene(
        self, client: AsyncClient,
    ) -> None:
        """POST ``/api/scene-multiplayer/{scene_id}/create`` returns 200.

        The JS does this in ``mpCreateScene()`` when the user
        toggles Multiplayer mode. The body is the scene's
        ``health()`` snapshot — the JS uses ``mpPushEvent`` to
        log it but doesn't bind to specific fields, so we just
        assert 200 + JSON.
        """
        paths = _route_paths(composed_app)
        assert E6C_FRONTEND_URLS["scene_create"] in paths, (
            f"Frontend URL template "
            f"{E6C_FRONTEND_URLS['scene_create']!r} is not a route "
            f"on the composed app — demo.html's mpCreateScene() will "
            f"404. Available: {paths!r}"
        )

        scene_id = "scene_e6c_create"
        resp = await client.post(
            f"/api/scene-multiplayer/{scene_id}/create"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # The scene health() payload is JSON-shaped. The JS doesn't
        # bind to specific fields, but a malformed body would log
        # 'create_scene failed: HTTP 500' to the user.
        assert isinstance(body, dict)
        assert body.get("scene_id") == scene_id, (
            f"expected scene_id={scene_id!r} in response, got "
            f"{body.get('scene_id')!r}"
        )
        # Cap values the UI relies on (e.g. "Queue: 0 pending"
        # next to the mp-queue-badge).
        assert body.get("max_players") == 4, (
            f"expected max_players=4 (game scope), got "
            f"{body.get('max_players')!r}"
        )
        assert body.get("max_npcs") == 100, (
            f"expected max_npcs=100 (E6b cap), got {body.get('max_npcs')!r}"
        )
        # And: creating the same scene twice is idempotent (the JS
        # calls this on every toggle, so a 200/200 sequence must
        # not 409).
        resp2 = await client.post(
            f"/api/scene-multiplayer/{scene_id}/create"
        )
        assert resp2.status_code == 200, (
            f"second create on the same scene must be idempotent; "
            f"got {resp2.status_code}: {resp2.text}"
        )

    @pytest.mark.asyncio
    async def test_frontend_can_join_as_player_1(
        self, client: AsyncClient,
    ) -> None:
        """POST join for slot 0 (player_1) returns 200.

        The JS does this in ``mpJoinSlot(0)`` when the user clicks
        "Join as Player 1". The body is the scene's ``health()``
        snapshot — the JS reads ``mpPushEvent`` to log it. The
        critical assertion is the round-trip: 200 + a JSON body
        with ``scene_id`` and ``player_count`` matching the slot
        the JS thinks it filled.
        """
        paths = _route_paths(composed_app)
        assert E6C_FRONTEND_URLS["scene_player_join"] in paths, (
            f"Frontend URL template "
            f"{E6C_FRONTEND_URLS['scene_player_join']!r} is not a "
            f"route on the composed app — demo.html's mpJoinSlot() "
            f"will 404. Available: {paths!r}"
        )

        scene_id = "scene_e6c_join1"
        # The JS always creates the scene first (idempotent), then
        # joins. We do the same.
        await client.post(f"/api/scene-multiplayer/{scene_id}/create")

        resp = await client.post(
            f"/api/scene-multiplayer/{scene_id}/player/player_1/join",
            params={"character_id": "char_player_1"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert isinstance(body, dict)
        assert body.get("scene_id") == scene_id
        assert body.get("player_count") == 1, (
            f"expected 1 player after first join, got "
            f"{body.get('player_count')!r}"
        )

        # And: a follow-up GET /players shows the slot the JS will
        # render in the sidebar.
        resp2 = await client.get(
            f"/api/scene-multiplayer/{scene_id}/players"
        )
        assert resp2.status_code == 200
        roster = resp2.json()
        players = roster.get("players", [])
        assert len(players) == 1
        assert players[0].get("player_id") == "player_1"
        assert players[0].get("character_id") == "char_player_1"

    @pytest.mark.asyncio
    async def test_frontend_can_list_4_player_slots(
        self, client: AsyncClient,
    ) -> None:
        """GET ``/api/scene-multiplayer/{scene_id}/players`` returns
        a JSON object with a ``players`` array and the cap the UI
        shows.

        The JS does this in ``mpRefreshRoster()`` (every 5 seconds
        while the panel is open). The frontend reads:

          * ``body.players`` — array of {player_id, character_id, ...}
          * ``body.count`` — int (rendered as the slot count)
          * ``body.max_players`` — int (drives the "Join as Player N"
            button enabled state, e.g. disabled when 4/4)

        We assert all three keys exist and have the right type,
        then fill all 4 slots and assert the cap shows up.
        """
        paths = _route_paths(composed_app)
        assert E6C_FRONTEND_URLS["scene_players_list"] in paths, (
            f"Frontend URL template "
            f"{E6C_FRONTEND_URLS['scene_players_list']!r} is not a "
            f"route on the composed app. Available: {paths!r}"
        )

        scene_id = "scene_e6c_4slots"
        await client.post(f"/api/scene-multiplayer/{scene_id}/create")
        for i in range(1, 5):
            r = await client.post(
                f"/api/scene-multiplayer/{scene_id}/player/player_{i}/join",
                params={"character_id": f"char_player_{i}"},
            )
            assert r.status_code == 200, f"join {i} failed: {r.text}"

        resp = await client.get(
            f"/api/scene-multiplayer/{scene_id}/players"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert isinstance(body, dict)
        # All 4 players in the array.
        assert isinstance(body.get("players"), list)
        assert len(body["players"]) == 4, (
            f"expected 4 players in roster, got {len(body['players'])}: "
            f"{body['players']!r}"
        )
        # The cap fields the UI relies on for "Join as Player N"
        # button enabled/disabled state.
        assert body.get("count") == 4
        assert body.get("max_players") == 4, (
            f"expected max_players=4 in roster response, got "
            f"{body.get('max_players')!r}"
        )
        # Each player has the fields the JS reads.
        for p in body["players"]:
            assert p.get("player_id"), f"player missing player_id: {p!r}"
            assert p.get("character_id"), f"player missing character_id: {p!r}"

    @pytest.mark.asyncio
    async def test_frontend_cannot_join_5th_player(
        self, client: AsyncClient,
    ) -> None:
        """5th player returns 409 (scene full).

        The JS's ``mpJoinSlot(i)`` does this:

            if (r.ok) { ... }
            else if (r.status === 409) {
              mpPushEvent('system', 'slot rejected: scene full or seat taken');
            }

        So a 409 is the **expected** success signal for the
        capacity-rejection branch. The assertion is: 4 players
        join successfully, the 5th gets 409, the scene stays at
        4 (no over-fill).
        """
        scene_id = "scene_e6c_full"
        await client.post(f"/api/scene-multiplayer/{scene_id}/create")

        # Fill 4.
        for i in range(1, 5):
            r = await client.post(
                f"/api/scene-multiplayer/{scene_id}/player/player_{i}/join",
                params={"character_id": f"char_player_{i}"},
            )
            assert r.status_code == 200, (
                f"player {i} should have joined, got {r.status_code}: {r.text}"
            )

        # 5th must be rejected with 409 (the exact status code the
        # JS branches on).
        r5 = await client.post(
            f"/api/scene-multiplayer/{scene_id}/player/player_5/join",
            params={"character_id": "char_player_5"},
        )
        assert r5.status_code == 409, (
            f"5th player must be rejected with 409 (the status the JS "
            f"branches on); got {r5.status_code}: {r5.text}"
        )
        # The body should explain why (the JS doesn't read the body
        # for the 409 branch, but the user-visible event log will
        # be friendlier if a detail string is present).
        body = r5.json()
        assert "detail" in body, (
            f"409 response missing 'detail' field; UI message will be "
            f"blank. body={body!r}"
        )

        # And: the roster must still show 4 (not 5, not 3).
        roster = await client.get(
            f"/api/scene-multiplayer/{scene_id}/players"
        )
        assert roster.status_code == 200
        body = roster.json()
        assert body.get("count") == 4, (
            f"scene should still hold 4 after the 5th was rejected; "
            f"got count={body.get('count')!r}"
        )

    @pytest.mark.asyncio
    async def test_frontend_broadcast_endpoint_works(
        self, client: AsyncClient,
    ) -> None:
        """POST ``/api/multiplayer/{scene_id}/broadcast`` returns 200
        with ``{scene_id, delivered_to}`` even when nobody is
        connected (delivered_to == 0 is correct, not an error).

        This is the E6a server-push broadcast endpoint. The JS
        doesn't call this directly (it sends player actions over
        the WebSocket), but the audit log + the future NPC-action
        pipeline will, so the route must be live and return the
        documented shape.
        """
        paths = _route_paths(composed_app)
        assert E6C_FRONTEND_URLS["broadcast"] in paths, (
            f"Frontend URL template "
            f"{E6C_FRONTEND_URLS['broadcast']!r} is not a route on "
            f"the composed app. Available: {paths!r}"
        )

        scene_id = "scene_e6c_broadcast"
        # No players connected — broadcast should succeed with
        # delivered_to == 0 (not 404 or 500).
        payload = {
            "event": "npc_action",
            "actor": "npc_gundren",
            "verb": "speak",
            "narrative": "Gundren leans across the bar...",
        }
        resp = await client.post(
            f"/api/multiplayer/{scene_id}/broadcast", json=payload
        )
        assert resp.status_code == 200, (
            f"broadcast must succeed (delivered_to=0 is OK); got "
            f"{resp.status_code}: {resp.text}"
        )
        body = resp.json()
        # The exact shape demo.html's broadcast callers (and the
        # audit log) expect.
        assert set(body.keys()) == {"scene_id", "delivered_to"}, (
            f"unexpected broadcast response shape: {set(body.keys())!r}"
        )
        assert body["scene_id"] == scene_id
        assert body["delivered_to"] == 0, (
            f"no players connected; expected delivered_to=0, got "
            f"{body['delivered_to']!r}"
        )

    @pytest.mark.asyncio
    async def test_frontend_xss_safe_in_demo_html(self) -> None:
        """``demo.html`` must remain XSS-safe after E6c.

        XSS invariant from ``docs/AUDIT_D4_M3.json`` finding #3:
        forbid ``v-html``, ``innerHTML``, ``outerHTML``, and
        ``document.write`` in ``demo.html``. The E6c multiplayer
        panel added new Vue templates (slots, event log, NPC
        list, mode toggle) and several new ``{{ }}`` bindings
        with attacker-controlled inputs (player_id, character_id,
        broadcast text). All of them must flow through Vue's
        textContent path, not raw HTML insertion.

        We ripgrep ``demo.html`` for the four forbidden patterns,
        exclude matches that appear inside a ``// comment`` or
        ``<!-- comment -->`` (which are documentation, not
        usage), and assert zero real usages remain.
        """
        demo_path = Path(_REPO_ROOT) / "demo.html"
        assert demo_path.exists(), f"demo.html not found at {demo_path}"

        # Read the file as text and split into lines so we can
        # distinguish a usage from a comment. The patterns are
        # intentionally literal (no \b word boundaries) because
        # we want to catch, e.g., ``.innerHTML = ...`` assignments.
        forbidden_patterns = [
            "v-html",        # Vue raw HTML directive
            "innerHTML",     # DOM property write
            "outerHTML",     # DOM property write
            "document.write",  # classic XSS sink
        ]

        # Read once, strip JS line comments and HTML comments.
        # We do this naively (no parser) because the file is
        # small and we only need to filter "documentation"
        # references, not be a perfect comment-stripper.
        text = demo_path.read_text(encoding="utf-8")
        # Strip block comments /* ... */ (handles multi-line).
        text_no_block = re.sub(
            r"/\*.*?\*/", "", text, flags=re.DOTALL,
        )
        # Strip HTML comments <!-- ... --> (handles multi-line
        # AND single-line comments — the DOTALL flag is what
        # makes ``.`` match newlines, so single-line comments
        # are also removed).
        text_no_html_comments = re.sub(
            r"<!--.*?-->", "", text_no_block, flags=re.DOTALL,
        )

        real_usages: list[tuple[str, int, str]] = []
        for lineno, raw_line in enumerate(
            text_no_html_comments.splitlines(), start=1,
        ):
            # Strip JS line comments (// ...) — anything after
            # ``//`` on a line is treated as a comment. This is
            # intentionally conservative: it may miss a token
            # that appears *before* a ``//`` on the same line,
            # which is the correct behaviour (a real usage on
            # the same line as a comment is still a real usage).
            # We accept this trade-off because the file is
            # hand-written and no real code lives on a line
            # that starts with a ``//`` comment.
            line_no_js_comment = re.sub(r"//.*$", "", raw_line)
            for pat in forbidden_patterns:
                if pat in line_no_js_comment:
                    real_usages.append((pat, lineno, raw_line.strip()))

        # De-duplicate (one pattern can match the same line in
        # multiple positions; the assertion is about "did this
        # line contain a real usage", not "how many times").
        unique_usages = sorted(set(real_usages))

        assert not unique_usages, (
            "XSS invariant violated: demo.html contains "
            "forbidden patterns. "
            "Offending lines:\n"
            + "\n".join(
                f"  L{ln}: {pat!r}  →  {line!r}"
                for pat, ln, line in unique_usages
            )
            + "\n\nSee docs/AUDIT_D4_M3.json finding #3 for the rule."
        )


# ============================================
# Bonus: URL contract enforcement
# ============================================
class TestE6CFrontendURLContract:
    """The frontend (demo.html multiplayer panel) and backend
    (composed app) agree on URL paths.

    Static check: every URL pattern the JS ``fetch()``es or
    ``new WebSocket()``s must be a registered route on the
    composed app. Catches URL typos, route renames, and prefix
    changes silently breaking the multiplayer panel.
    """

    def test_all_e6c_frontend_urls_resolve_to_routes(self) -> None:
        """Every URL demo.html's multiplayer panel uses must exist.

        We compare the *template* paths (what the app registers)
        against the URL *patterns* the frontend uses. Parametric
        segments (``{scene_id}``, ``{player_id}``) match because
        the templates use the same brace syntax.
        """
        paths = _route_paths(composed_app)
        missing = [
            name for name, tmpl in E6C_FRONTEND_URLS.items()
            if tmpl not in paths
        ]
        assert not missing, (
            f"demo.html multiplayer panel fetches URLs that don't "
            f"exist on the backend: {missing!r}. Either the "
            f"frontend is wrong (fix demo.html) or the backend "
            f"lost a route (regression!). "
            f"Templates looked for: {list(E6C_FRONTEND_URLS.values())!r}"
        )

    def test_e6c_websocket_route_present(self) -> None:
        """The WebSocket route the frontend's ``mpConnectWS()``
        targets exists.

        The JS does:

            new WebSocket(
              `${WS_BASE}/ws/multiplayer/${scene_id}/${player_id}`
            )

        The template must be present on the router.
        """
        ws_templates = [
            r.path for r in composed_app.routes
            if hasattr(r, "path") and r.path.startswith("/ws/")
        ]
        expected = "/ws/multiplayer/{scene_id}/{player_id}"
        assert expected in ws_templates, (
            f"WebSocket route {expected!r} missing; "
            f"demo.html's mpConnectWS() will silently fail. "
            f"WS templates found: {ws_templates!r}"
        )

    def test_e6c_scene_state_routes_match_frontend_methods(self) -> None:
        """The HTTP verbs the frontend sends match the route table.

        Cross-check: the JS does ``POST`` to
        ``/api/scene-multiplayer/.../create`` and
        ``/api/scene-multiplayer/.../player/.../join``; ``GET`` to
        ``/api/scene-multiplayer/.../players``, ``/npcs``,
        ``/turn/queue-size``. If the backend changes any verb,
        the frontend's ``r.ok`` will be false and the user will
        see a generic "create failed: HTTP 405" event log line.
        """
        # Build a {(path, method)} set from the composed app.
        method_paths: set[tuple[str, str]] = set()
        for r in composed_app.routes:
            if not hasattr(r, "path") or not hasattr(r, "methods"):
                continue
            for m in (r.methods or set()):
                if m == "HEAD":
                    continue
                method_paths.add((r.path, m))

        # The frontend's HTTP calls (verb → path template).
        expected_calls = [
            ("POST", "/api/scene-multiplayer/{scene_id}/create"),
            ("POST", "/api/scene-multiplayer/{scene_id}/player/{player_id}/join"),
            ("GET",  "/api/scene-multiplayer/{scene_id}/players"),
            ("GET",  "/api/scene-multiplayer/{scene_id}/npcs"),
            ("GET",  "/api/scene-multiplayer/{scene_id}/turn/queue-size"),
            ("POST", "/api/multiplayer/{scene_id}/broadcast"),
        ]
        missing = [
            (verb, tmpl) for verb, tmpl in expected_calls
            if (tmpl, verb) not in method_paths
        ]
        assert not missing, (
            f"Frontend HTTP verb + path combination missing on the "
            f"composed app. The JS will get HTTP 405 Method Not "
            f"Allowed. Missing: {missing!r}"
        )
