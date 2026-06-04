"""
Integration tests for the persistence dispatcher.

These tests verify:
1. The API code path goes through ``persistence.get_store()`` (not
   ``backend.store.store`` directly), so the backend can be swapped
   without touching the API.
2. In "memory" mode, data is held in the in-process store and is lost on
   "restart" (clearing the singleton). This is the documented behavior
   and is what the default ``persistence_mode`` setting provides.
3. In "database" mode, data persists across engine disposal/restart.

The tests use:
- ``unittest.mock.patch`` to spy on the dispatcher
- Per-test temporary SQLite databases for the database mode
"""
from __future__ import annotations

import os
import sys
import asyncio
import importlib
from unittest.mock import patch

import pytest
import pytest_asyncio

# Repo root on sys.path so ``import backend.*`` works
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ============================================
# Per-test database fixtures
# ============================================

@pytest_asyncio.fixture
async def fresh_sqlite_db(monkeypatch, tmp_path):
    """Per-test SQLite DB; resets engine + in-memory store between tests."""
    db_path = tmp_path / "persistence_integration.db"
    monkeypatch.setenv("SANDBOX_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    # Ensure the database mode is used for this test
    monkeypatch.setenv("SANDBOX_PERSISTENCE_MODE", "database")

    from backend import db as db_mod
    from backend import store as store_mod
    from backend import persistence as persistence_mod

    # Drop the engine + clear in-memory store + clear the dispatcher cache
    await db_mod.dispose_engine()
    store_mod.store.characters.clear()
    store_mod.store.scenes.clear()
    store_mod.store.worlds.clear()
    persistence_mod.reset_backend_cache()

    yield db_path

    # Teardown
    await db_mod.dispose_engine()
    store_mod.store.characters.clear()
    store_mod.store.scenes.clear()
    store_mod.store.worlds.clear()
    persistence_mod.reset_backend_cache()


@pytest_asyncio.fixture
async def fresh_memory(monkeypatch):
    """Reset the in-memory store and dispatcher cache (default mode)."""
    monkeypatch.setenv("SANDBOX_PERSISTENCE_MODE", "memory")
    from backend import store as store_mod
    from backend import persistence as persistence_mod

    store_mod.store.characters.clear()
    store_mod.store.scenes.clear()
    store_mod.store.worlds.clear()
    persistence_mod.reset_backend_cache()
    yield
    store_mod.store.characters.clear()
    store_mod.store.scenes.clear()
    store_mod.store.worlds.clear()
    persistence_mod.reset_backend_cache()


def _make_character(character_id: str = "char_int_001", **extras) -> dict:
    base = {
        "character_id": character_id,
        "name": "Integration Hero",
        "world_id": "w_int",
        "physical": {"stamina_level": "fresh", "health_status": "healthy"},
        "mental": {"morale_level": "neutral"},
        "inventory": {"items": []},
        "memories": [],
        "relationships": {},
    }
    base.update(extras)
    return base


# ============================================
# Test 1 — API code path actually uses persistence
# ============================================

class TestApiUsesPersistence:
    """The API endpoints must go through persistence.get_store(), not the
    global InMemoryStore directly. We verify by patching the dispatcher
    and confirming the API code calls it."""

    def test_api_action_uses_persistence_dispatcher(self):
        """Importing backend.api.action should call persistence.get_store()
        exactly once at module load."""
        from backend import persistence as persistence_mod
        with patch.object(
            persistence_mod, "get_store", wraps=persistence_mod.get_store
        ) as spy:
            # Re-import to trigger module-level call
            import importlib
            from backend.api import action
            importlib.reload(action)
            assert spy.call_count >= 1, (
                "action.py must call persistence.get_store() to resolve its "
                "store reference (dispatcher not used)"
            )

    def test_api_character_uses_persistence_dispatcher(self):
        from backend import persistence as persistence_mod
        with patch.object(
            persistence_mod, "get_store", wraps=persistence_mod.get_store
        ) as spy:
            from backend.api import character
            importlib.reload(character)
            assert spy.call_count >= 1

    def test_api_scene_uses_persistence_dispatcher(self):
        from backend import persistence as persistence_mod
        with patch.object(
            persistence_mod, "get_store", wraps=persistence_mod.get_store
        ) as spy:
            from backend.api import scene
            importlib.reload(scene)
            assert spy.call_count >= 1

    def test_api_world_uses_persistence_dispatcher(self):
        from backend import persistence as persistence_mod
        with patch.object(
            persistence_mod, "get_store", wraps=persistence_mod.get_store
        ) as spy:
            from backend.api import world
            importlib.reload(world)
            assert spy.call_count >= 1

    def test_api_does_not_import_inmemory_store_directly(self):
        """The four API files must NOT import the InMemoryStore singleton
        directly. They should import the persistence dispatcher only."""
        for module_name in ("action", "character", "scene", "world"):
            path = os.path.join(
                _PROJECT_ROOT, "backend", "api", f"{module_name}.py"
            )
            with open(path, encoding="utf-8") as f:
                src = f.read()
            # The historical bug was `from ..store import store`.
            assert "from ..store import store" not in src, (
                f"backend/api/{module_name}.py still imports the InMemoryStore "
                f"directly via 'from ..store import store' — must go through "
                f"persistence.get_store() instead"
            )
            # The new contract requires the dispatcher import.
            assert "from .. import persistence" in src, (
                f"backend/api/{module_name}.py must import the persistence "
                f"dispatcher to call get_store()"
            )

    @pytest.mark.asyncio
    async def test_api_save_character_calls_store_save_character(self, fresh_memory):
        """End-to-end: create a character via the API and confirm the
        dispatcher-returned backend actually received the call."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.api.character import router as character_router
        from backend import persistence as persistence_mod
        from backend import store as store_mod

        app = FastAPI()
        app.include_router(character_router, prefix="/api/character", tags=["character"])
        client = TestClient(app)

        # Spy on the *inner* store.save_character method (the actual sink)
        with patch.object(
            store_mod.store, "save_character", wraps=store_mod.store.save_character
        ) as spy:
            resp = client.post(
                "/api/character/",
                json={
                    "character_id": "char_int_api_001",
                    "name": "API Hero",
                    "world_id": "w_int",
                    "physical": {"stamina_level": "fresh", "health_status": "healthy"},
                    "mental": {"morale_level": "neutral"},
                },
            )
            assert resp.status_code == 200, resp.text
            assert spy.call_count == 1, (
                f"Expected store.save_character to be called exactly once, "
                f"got {spy.call_count}"
            )
            # The character must be in the in-memory store
            assert "char_int_api_001" in store_mod.store.characters


# ============================================
# Test 2 — Memory mode: data is lost on "restart"
# ============================================

class TestMemoryMode:
    """Default mode: in-process InMemoryStore. Restarting the process (or
    clearing the singleton) loses data. This test simulates restart by
    calling the store.clear() helper and confirming the data is gone."""

    @pytest.mark.asyncio
    async def test_data_lost_on_restart_in_memory_mode(self, fresh_memory):
        from backend import persistence as persistence_mod
        from backend import store as store_mod

        backend = persistence_mod.get_store()
        # Memory mode → backend is the AsyncInMemoryStore wrapper
        assert persistence_mod.current_mode() == "memory"

        char = _make_character("char_mem_001")
        await backend.save_character(char)
        # Sanity: present in the in-memory store
        assert "char_mem_001" in store_mod.store.characters
        loaded = await backend.get_character("char_mem_001")
        assert loaded is not None
        assert loaded["character_id"] == "char_mem_001"

        # Simulate restart: wipe the in-memory store
        store_mod.store.characters.clear()
        store_mod.store.scenes.clear()
        store_mod.store.worlds.clear()

        # The data is gone — this is the documented limitation
        loaded_after = await backend.get_character("char_mem_001")
        assert loaded_after is None, (
            "After 'restart' (clearing the in-memory store), the character "
            "must be gone — this confirms the documented behaviour for "
            "memory mode (in-process store, no persistence across restarts)"
        )

    @pytest.mark.asyncio
    async def test_memory_mode_uses_inmemory_store(self, fresh_memory):
        """In memory mode, get_store() returns the in-process store wrapper."""
        from backend import persistence as persistence_mod
        from backend import store as store_mod

        backend = persistence_mod.get_store()
        # The AsyncInMemoryStore wrapper exposes the underlying InMemoryStore
        # via .inner; this is the same singleton as backend.store.store.
        assert hasattr(backend, "inner"), (
            "AsyncInMemoryStore must expose the wrapped InMemoryStore via "
            "`.inner` for test introspection"
        )
        assert backend.inner is store_mod.store


# ============================================
# Test 3 — Database mode: data persists across "restart"
# ============================================

class TestDatabaseMode:
    """In database mode, data persists across engine disposal/restart
    because it lives in the SQLAlchemy-backed tables."""

    @pytest.mark.asyncio
    async def test_data_persists_in_db_mode(self, fresh_sqlite_db):
        from backend import persistence as persistence_mod
        from backend import db as db_mod

        # Sanity: we're in database mode
        assert persistence_mod.current_mode() == "database"

        backend = persistence_mod.get_store()
        char = _make_character("char_db_001", name="DBHero")
        await backend.save_character(char)

        # Confirm it's reachable
        loaded = await backend.get_character("char_db_001")
        assert loaded is not None
        assert loaded["character_id"] == "char_db_001"
        assert loaded["name"] == "DBHero"

        # Simulate restart: dispose the engine, clear the cache, and
        # re-resolve the backend. The DB file persists, so the data is
        # still there.
        await db_mod.dispose_engine()
        persistence_mod.reset_backend_cache()

        # The in-memory store is untouched (we never wrote to it)
        backend2 = persistence_mod.get_store()
        # Should be a fresh DBStore instance bound to the same SQLite file
        loaded_after = await backend2.get_character("char_db_001")
        assert loaded_after is not None, (
            "After 'restart' (engine dispose + cache clear), the character "
            "must still be present in the database"
        )
        assert loaded_after["character_id"] == "char_db_001"
        assert loaded_after["name"] == "DBHero"

    @pytest.mark.asyncio
    async def test_db_mode_uses_dbstore(self, fresh_sqlite_db):
        """In database mode, get_store() returns the DBStore instance."""
        from backend import persistence as persistence_mod
        from backend.persistence_db import db_store

        backend = persistence_mod.get_store()
        assert backend is db_store, (
            "In 'database' mode, get_store() must return the DBStore "
            "singleton from backend.persistence_db"
        )

    @pytest.mark.asyncio
    async def test_db_mode_scenes_persist(self, fresh_sqlite_db):
        """Scenes also persist across restart in database mode."""
        from backend import persistence as persistence_mod
        from backend import db as db_mod

        backend = persistence_mod.get_store()
        for r in (1, 2, 3):
            await backend.save_scene(
                "char_db_002",
                {
                    "round": r,
                    "character_id": "char_db_002",
                    "narrative": f"DB scene {r}",
                    "choices": [{"id": f"opt_{r:02d}"}],
                },
            )

        # Simulate restart
        await db_mod.dispose_engine()
        persistence_mod.reset_backend_cache()

        backend2 = persistence_mod.get_store()
        history = await backend2.get_scene_history("char_db_002", limit=10)
        assert len(history) == 3
        assert [s["round"] for s in history] == [1, 2, 3]

        latest = await backend2.get_latest_scene("char_db_002")
        assert latest is not None
        assert latest["round"] == 3


# ============================================
# Test 4 — Dispatcher behaviour
# ============================================

class TestDispatcher:
    """The dispatcher itself: mode switching + caching."""

    def test_default_mode_is_memory(self):
        from backend import persistence as persistence_mod
        # Default settings.persistence_mode is "memory"
        assert persistence_mod.current_mode() == "memory"

    def test_env_var_overrides_settings(self, monkeypatch):
        monkeypatch.setenv("SANDBOX_PERSISTENCE_MODE", "database")
        from backend import persistence as persistence_mod
        # resolve fresh
        assert persistence_mod._resolve_mode() == "database"
        # cleanup
        monkeypatch.delenv("SANDBOX_PERSISTENCE_MODE", raising=False)

    def test_caching_returns_same_instance(self, monkeypatch):
        """The dispatcher must return the same backend instance on repeated
        calls (cache hit) — otherwise we'd accumulate DB connections /
        in-memory state per call."""
        monkeypatch.setenv("SANDBOX_PERSISTENCE_MODE", "memory")
        from backend import persistence as persistence_mod
        persistence_mod.reset_backend_cache()
        a = persistence_mod.get_store()
        b = persistence_mod.get_store()
        assert a is b

    def test_reset_backend_cache_returns_fresh(self, monkeypatch):
        """``reset_backend_cache()`` clears the dispatcher cache. A subsequent
        ``get_store()`` re-resolves and re-wraps the backend. In memory mode
        the wrapped InMemoryStore is the module-level singleton in
        ``backend.store`` so the inner object is the same; in database mode
        the ``db_store`` singleton is also reused. We assert the cache was
        actually cleared (i.e. the lookup runs again, not skipped) by
        checking the cache dict is empty after reset."""
        monkeypatch.setenv("SANDBOX_PERSISTENCE_MODE", "memory")
        from backend import persistence as persistence_mod
        persistence_mod.reset_backend_cache()
        persistence_mod.get_store()  # populate cache
        assert persistence_mod._BACKEND_CACHE, "Cache should be populated"
        persistence_mod.reset_backend_cache()
        assert not persistence_mod._BACKEND_CACHE, (
            "Cache should be empty after reset_backend_cache()"
        )
