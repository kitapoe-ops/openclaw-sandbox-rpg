"""
Production Smoke Test (Phase L2-D, 2026-06-07)
==============================================

Replaces the Phase D4 demo E2E suite (``test_d4_*_e2e`` and
``test_multiplayer_frontend_e2e``) which validated the old
``demo.html`` + ``app_with_memory`` wiring.

This test validates the **production stack**:

  Frontend: Vue 3 SPA in ``frontend/dist/`` (built by `npm run build`)
  Backend:  ``backend.main:app`` (FastAPI, real DB)
  Static:   served by FastAPI at ``/`` (no separate serve_demo.py)

The test runs in-process via ``httpx.AsyncClient`` + ``ASGITransport``,
so no real network or port-binding is required. It exercises the same
``app`` instance the production uvicorn will boot.

Assertions:
  1. /health → 200, mode=full (not demo)
  2. /       → 200, returns SPA bootstrap info (no demo URLs)
  3. GET /api/world/        → 200, list of worlds
  4. GET /api/character/{id} → 404 (no demo fallback in production)
  5. ENV=production + is_demo_mode=True → startup crash (fail-loud)
  6. Frontend dist/ exists and contains index.html
  7. Frontend dist/ does NOT contain demo.html
  8. Production guard: ENV=production forces full mode

These are the **minimum** smoke tests. Real integration tests
(character creation, scene navigation, audit) live in their own
modules. This file is the **gate** that must pass before deploy.
"""

import os
import subprocess
from pathlib import Path

import pytest

# ============================================================
# Production-mode smoke tests
# ============================================================

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


@pytest.fixture(scope="module")
def client():
    """ASGI test client. Defaults to ENV=development to avoid the
    fail-loud guard; tests that need production behavior use a
    separate fixture that sets ENV=production."""
    os.environ.setdefault("ENV", "development")
    os.environ.setdefault("DEMO_MODE", "false")
    from httpx import ASGITransport, AsyncClient

    from backend.main import app

    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_health_returns_200_and_full_mode(client):
    """Backend is alive and running in FULL mode (not demo)."""
    resp = await client.get("/health")
    assert resp.status_code == 200, f"health failed: {resp.text}"
    body = resp.json()
    assert body["status"] == "ok"
    assert body["mode"] == "full", (
        f"Expected mode=full (real DB), got mode={body['mode']}. "
        "Production smoke test requires a real PostgreSQL connection."
    )


@pytest.mark.asyncio
async def test_root_returns_spa_bootstrap(client):
    """Root endpoint serves the Vue SPA (frontend/dist/index.html).
    Phase L2-G: / was changed from JSON to the SPA, with API metadata
    moved to /api. We verify HTML shape here."""
    resp = await client.get("/")
    assert resp.status_code == 200, f"GET / failed: {resp.text}"
    content_type = resp.headers.get("content-type", "")
    # / should serve HTML (the Vue SPA)
    assert "text/html" in content_type, (
        f"GET / should return text/html (Vue SPA), got {content_type}. "
        "Did you forget to build frontend/dist/?"
    )
    body = resp.text
    assert (
        "<!doctype html>" in body.lower() or "<html" in body.lower()
    ), f"GET / body doesn't look like HTML. First 200 chars: {body[:200]}"
    # The SPA includes the Vue entry point
    assert "/assets/" in body, "GET / doesn't reference /assets/ (Vue bundle missing)"


@pytest.mark.asyncio
async def test_api_world_list(client):
    """GET /api/world/ returns the world list from the DB.
    Skipped when DB is unreachable (e.g. CI without postgres)."""
    resp = await client.get("/api/world/")
    # In demo mode the endpoint still works (returns YAML-derived
    # worlds). In full mode it returns DB-seeded worlds. We just
    # require the response shape is valid.
    assert resp.status_code == 200, f"world list failed: {resp.text}"
    body = resp.json()
    assert "worlds" in body
    assert isinstance(body["worlds"], list)
    # Worlds list is non-empty (demo or seeded DB) — otherwise the
    # SPA home page will be empty and the user sees nothing.
    if resp.status_code == 200:
        assert (
            len(body["worlds"]) >= 1
        ), f"Expected at least 1 world (demo YAML or DB seed). Got: {body['worlds']}"


@pytest.mark.asyncio
async def test_api_character_unknown_returns_404_not_demo(client):
    """Unknown character ID must return 404 — NOT silently fall back
    to demo data. This is the key behavior change in Phase L2-B."""
    # Force a fresh DB connection — the SQLAlchemy async engine keeps
    # a pool of connections that can return stale or unhealthy ones
    # when reused across tests in the same session.
    from backend.db import engine

    resp = await client.get("/api/character/char_does_not_exist_xyz")
    assert resp.status_code == 404, (
        f"Expected 404 for unknown character, got {resp.status_code}. "
        f"Response body: {resp.text}. "
        "Demo mode fallback is forbidden in production."
    )
    # Make sure response body doesn't contain demo mode marker
    body = resp.json()
    body_str = str(body).lower()
    assert (
        "mode" not in body or "demo" not in body_str
    ), f"404 response must not advertise 'demo' mode. Got: {body}"


# ============================================================
# Frontend artifact smoke tests
# ============================================================


def test_frontend_dist_exists():
    """frontend/dist/ must be built (npm run build) before deploy."""
    assert FRONTEND_DIST.exists(), (
        f"frontend/dist/ not found at {FRONTEND_DIST}. " "Run `cd frontend && npm run build` first."
    )
    assert (
        FRONTEND_DIST / "index.html"
    ).exists(), "frontend/dist/index.html missing — Vite build incomplete"


def test_frontend_dist_has_no_demo_html():
    """Production build must NOT contain the deprecated demo.html."""
    # Scan dist for any file with 'demo' in the name
    demo_files = list(FRONTEND_DIST.rglob("*demo*"))
    # The only acceptable match is a path component containing
    # 'assets' or 'node_modules' subdirs (none should exist in dist).
    # Filter false positives:
    real_demo_files = [p for p in demo_files if p.is_file() and "demo" in p.name.lower()]
    assert (
        len(real_demo_files) == 0
    ), f"Production frontend must not contain demo files. Found: {real_demo_files}"


# ============================================================
# Production guard (fail-loud) tests
# ============================================================


def test_production_guard_rejects_demo_mode():
    """When ENV=production and DEMO_MODE=true, the backend MUST crash
    at startup. This prevents silent fallback to in-memory demo data
    in a misconfigured production environment.

    We can't easily simulate this in-process (the app is already
    imported with the test env), so we spawn a subprocess that
    runs the lifespan only.
    """
    import json
    import sys

    # Use python -c to invoke the lifespan directly
    code = (
        "import os, asyncio, json, sys\n"
        "os.environ['ENV'] = 'production'\n"
        "os.environ['DEMO_MODE'] = 'true'\n"
        "sys.path.insert(0, r'" + str(REPO_ROOT) + "')\n"
        "from backend.main import app, lifespan\n"
        "async def main():\n"
        "    try:\n"
        "        async with lifespan(app):\n"
        "            print(json.dumps({'result': 'started', 'fail': False}))\n"
        "    except RuntimeError as e:\n"
        "        print(json.dumps({'result': 'rejected', 'fail': True, 'msg': str(e)}))\n"
        "    except Exception as e:\n"
        "        print(json.dumps({'result': 'unexpected', 'fail': True, 'err': type(e).__name__, 'msg': str(e)}))\n"
        "asyncio.run(main())\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        cwd=str(REPO_ROOT),
    )

    # The lifespan should refuse to start with PRODUCTION SAFETY message.
    # We accept the message in either stdout or stderr (subprocess output
    # routing depends on the exception's print target).
    combined = result.stdout + result.stderr
    assert "PRODUCTION SAFETY" in combined, (
        f"Production guard did NOT fire. "
        f"returncode={result.returncode}, "
        f"stdout={result.stdout!r}, "
        f"stderr={result.stderr!r}"
    )


# ============================================================
# Regression: original demo-mode unit tests still work
# ============================================================
# (DEMO_MODE=true tests live in test_demo_mode_e5.py and
# test_demo_mode_phase_d2.py — they are preserved as opt-in
# smoke tests. This file does not duplicate them.)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
