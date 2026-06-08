import os
import sys
import shutil
import pytest
import pytest_asyncio
from pathlib import Path

# Ensure backend directory is in the path
# __file__ is backend/tests/conftest.py
# parent is backend/tests, parent.parent is backend, parent.parent.parent is repo_root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "backend"))


@pytest.fixture(scope="session", autouse=True)
def setup_mock_frontend():
    """
    Session-level fixture that pre-creates a mock frontend/dist directory with index.html
    at the actual repo root if it does not exist (for CI).
    """
    dist_dir = _REPO_ROOT / "frontend" / "dist"
    mocked_dist = False

    if not dist_dir.exists():
        dist_dir.mkdir(parents=True, exist_ok=True)
        # Ensure we also create the assets directory so main.py mount works
        (dist_dir / "assets").mkdir(parents=True, exist_ok=True)
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

    yield

    # Clean up mock frontend directory
    if mocked_dist and dist_dir.exists():
        try:
            shutil.rmtree(dist_dir)
            print("[conftest] Cleaned up mock frontend/dist directory.")
        except Exception as e:
            print(f"[conftest] Failed to clean up mock frontend/dist: {e}")


@pytest_asyncio.fixture(autouse=True)
async def autouse_db_init():
    """
    Function-level autouse fixture to initialize DB tables safely within
    the event loop of the current running test, and clean up connections
    afterwards to prevent event loop mismatch issues.
    """
    from backend.db import init_db, engine

    try:
        await init_db()
    except Exception as e:
        print(f"[conftest] Database initialization failed: {e}")

    yield

    try:
        await engine.dispose()
    except Exception as e:
        print(f"[conftest] Database engine dispose failed: {e}")
