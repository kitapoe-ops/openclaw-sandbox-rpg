import os
import sys
import shutil
import pytest
import pytest_asyncio
import json
from pathlib import Path

# Ensure backend directory is in the path
# __file__ is backend/tests/conftest.py
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "backend"))

# Global flag to track if mock frontend was created by session hooks
_MOCKED_DIST_DIR = False

# 1. Create mock frontend immediately at import time.
# This guarantees it exists before other test files import backend.main at top-level.
dist_dir = _REPO_ROOT / "frontend" / "dist"
if not dist_dir.exists():
    dist_dir.mkdir(parents=True, exist_ok=True)
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
        encoding="utf-8"
    )
    _MOCKED_DIST_DIR = True
    print(f"\n[conftest] Top-level: Created mock frontend/dist directory at: {dist_dir}")


def pytest_sessionstart(session):
    """
    Hook called before any tests are run.
    This guarantees PostgreSQL tables are created and seeded with default World/Scene using a temporary engine,
    preventing loop mismatch issues with the global engine.
    """
    # 2. Pre-initialize and seed DB using a temporary engine
    import asyncio
    
    async def init_and_seed_db():
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        from backend.db import _build_database_url, Base
        from backend.scenes_demo import DEMO_SCENE, DEMO_STARTER
        
        # Import models so Base metadata has all table definitions registered
        import backend.models  # noqa: F401
        
        db_url = _build_database_url()
        temp_engine = create_async_engine(db_url)
        
        try:
            async with temp_engine.begin() as conn:
                # Create all tables
                await conn.run_sync(Base.metadata.create_all)
                
                # Seed World
                await conn.execute(
                    text(
                        "INSERT INTO worlds (id, name, version, config, is_active, created_at, updated_at) "
                        "VALUES (:id, :name, :version, CAST(:config AS jsonb), :is_active, now(), now()) "
                        "ON CONFLICT (id) DO NOTHING"
                    ),
                    {
                        "id": DEMO_STARTER["world_id"],
                        "name": "被遺忘嘅國度 — 凡達林地區",
                        "version": "D&D_5e_SRD_v5.1.0",
                        "config": json.dumps({"yaml_path": "worlds/dnd_5e_forgotten_realms.yaml"}),
                        "is_active": True,
                    }
                )
                
                # Seed Scene
                await conn.execute(
                    text(
                        "INSERT INTO scenes (id, world_id, name, description, location_tag, environment_tags, active_npcs, atmosphere, is_dynamic, created_at, updated_at) "
                        "VALUES (:id, :world_id, :name, :description, :location_tag, CAST(:environment_tags AS jsonb), CAST(:active_npcs AS jsonb), :atmosphere, :is_dynamic, now(), now()) "
                        "ON CONFLICT (id) DO NOTHING"
                    ),
                    {
                        "id": DEMO_SCENE["scene_id"],
                        "world_id": DEMO_STARTER["world_id"],
                        "name": "凡達林鎮 (Phandalin Town)",
                        "description": DEMO_SCENE["scene_narrative"],
                        "location_tag": "settlement",
                        "environment_tags": json.dumps(["outdoor", "settlement", "town", "frontier"]),
                        "active_npcs": json.dumps([
                            "npc_gundren",
                            "npc_halia",
                            "npc_sister_garaele",
                            "npc_redbrand_ringleader",
                            "npc_injured_traveler_01",
                        ]),
                        "atmosphere": "tense",
                        "is_dynamic": False,
                    }
                )
        finally:
            await temp_engine.dispose()
            
    print("[conftest] pytest_sessionstart: Initializing and seeding database...")
    try:
        # Use asyncio.run safely since no event loop is running yet during sessionstart
        asyncio.run(init_and_seed_db())
        print("[conftest] pytest_sessionstart: Database pre-initialization complete.")
    except Exception as e:
        print(f"[conftest] pytest_sessionstart: Database seeding failed: {e}")
        raise e

def pytest_sessionfinish(session, exitstatus):
    """
    Hook called after all tests have completed. Clean up the mock frontend.
    """
    global _MOCKED_DIST_DIR
    dist_dir = _REPO_ROOT / "frontend" / "dist"
    
    if _MOCKED_DIST_DIR and dist_dir.exists():
        try:
            shutil.rmtree(dist_dir)
            print("\n[conftest] pytest_sessionfinish: Cleaned up mock frontend/dist directory.")
        except Exception as e:
            print(f"\n[conftest] pytest_sessionfinish: Failed to clean up mock frontend/dist: {e}")

@pytest_asyncio.fixture(autouse=True)
async def autouse_db_cleanup():
    """
    Function-level autouse fixture to clean up database connections after each test.
    This ensures that connections bound to a finished test event loop do not leak
    into subsequent tests running on different event loops.
    """
    yield
    
    from backend.db import engine
    try:
        await engine.dispose()
    except Exception as e:
        print(f"[conftest] Database engine dispose failed: {e}")
