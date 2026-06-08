import os
import sys
import asyncio
import shutil
import pytest
from pathlib import Path

# Ensure backend directory is in the path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """
    Session-level fixture that:
    1. Pre-creates a mock frontend/dist directory with index.html if it does not exist (for CI).
    2. Runs database migrations/initialization (init_db) on the Postgres test container.
    """
    # 1. Setup mock frontend if missing
    repo_root = Path(_REPO_ROOT)
    dist_dir = repo_root / "frontend" / "dist"
    mocked_dist = False

    if not dist_dir.exists():
        dist_dir.mkdir(parents=True, exist_ok=True)
        index_html = dist_dir / "index.html"
        index_html.write_text(
            "<!doctype html>\n"
            "<html>\n"
            "  <head>\n"
            "    <title>Mock SPA</title>\n"
            "    <script type='module' src='/assets/index.js'></script>\n"
            "  </head>\n"
            "  <body>\n"
            "    <div id='app'></div>\n"
            "  </body>\n"
            "</html>",
            encoding="utf-8",
        )
        mocked_dist = True
        print(f"\n[conftest] Created mock frontend/dist directory at: {dist_dir}")

    # 2. Initialize PostgreSQL tables
    from backend.db import init_db, engine

    print("[conftest] Initializing database tables...")

    async def run_init_and_dispose():
        await init_db()
        await engine.dispose()

    try:
        asyncio.run(run_init_and_dispose())
        print("[conftest] Database initialization complete.")
    except Exception as e:
        print(f"[conftest] Database initialization failed/skipped: {e}")

    yield

    # Clean up mock frontend directory
    if mocked_dist and dist_dir.exists():
        try:
            shutil.rmtree(dist_dir)
            print("[conftest] Cleaned up mock frontend/dist directory.")
        except Exception as e:
            print(f"[conftest] Failed to clean up mock frontend/dist: {e}")
