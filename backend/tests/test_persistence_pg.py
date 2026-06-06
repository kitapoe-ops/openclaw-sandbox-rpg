"""
Unit tests for backend/persistence_pg.py
==========================================

Phase B3 — PostgreSQL Persistence Adapter Skeleton.

These tests use aiosqlite (NOT real Postgres) so they run anywhere
without external services. The dialect that ships with SQLAlchemy +
aiosqlite is enough to exercise the ORM contract that the Postgres
adapter exposes (create_all, JSON columns, FK indexes, CRUD).

Mirrors the test_db_race.py convention:
  * repo root on sys.path
  * @pytest.mark.asyncio on each async test
  * one fresh engine per test via fixture
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

# Ensure repo root is on sys.path (mirrors test_db_race.py convention)
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.persistence_pg import (  # noqa: E402
    PostgresPersistence,
    get_persistence_mode,
)


# ============================================
# Helpers / fixtures
# ============================================
@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    """Yield a per-test aiosqlite file URL, cleaned up automatically."""
    db_file = tmp_path / "pg_adapter_test.db"
    return f"sqlite+aiosqlite:///{db_file}"


@pytest_asyncio.fixture
async def pg(sqlite_url: str):
    """Yield a PostgresPersistence bound to a fresh aiosqlite file,
    then dispose the engine on teardown.

    NOTE: aiosqlite/SQLite does NOT enforce foreign keys unless each
    connection emits ``PRAGMA foreign_keys=ON``. The production adapter
    (asyncpg-backed) enforces FKs natively, but the test fixture must
    opt in explicitly or the FK-violation test would silently no-op.
    We register a SQLAlchemy ``connect`` event listener that runs the
    PRAGMA on every new DBAPI connection in this fixture only.
    """
    from sqlalchemy import event

    adapter = PostgresPersistence(sqlite_url)
    try:
        # Enable FK enforcement on every new SQLite connection.
        @event.listens_for(adapter._engine.sync_engine, "connect")
        def _enable_sqlite_fk(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

        yield adapter
    finally:
        await adapter.close()


# ============================================
# Env-switch tests
# ============================================
class TestGetPersistenceMode:
    """`get_persistence_mode()` reads PERSISTENCE_MODE from the env."""

    def test_get_persistence_mode_default(self, monkeypatch: pytest.MonkeyPatch):
        """No env var (and no leftover) → 'memory'."""
        monkeypatch.delenv("PERSISTENCE_MODE", raising=False)
        assert get_persistence_mode() == "memory"

    def test_get_persistence_mode_postgres(self, monkeypatch: pytest.MonkeyPatch):
        """PERSISTENCE_MODE=postgres → 'postgres'."""
        monkeypatch.setenv("PERSISTENCE_MODE", "postgres")
        assert get_persistence_mode() == "postgres"


# ============================================
# CRUD tests
# ============================================
@pytest.mark.asyncio
class TestCharacterRoundtrip:
    async def test_save_and_load_character(self, pg: PostgresPersistence):
        """Save a payload, load it back, assert deep-equal."""
        cid = "char-001"
        payload = {
            "name": "Aragorn",
            "hp": 42,
            "inventory": ["anduril", "ring"],
            "nested": {"a": 1, "b": [1, 2, 3]},
        }

        await pg.save_character(cid, payload)
        loaded = await pg.load_character(cid)

        assert loaded is not None
        assert loaded == payload

    async def test_delete_character(self, pg: PostgresPersistence):
        """Delete removes the row; subsequent load returns None."""
        cid = "char-002"
        await pg.save_character(cid, {"name": "Boromir"})
        assert await pg.load_character(cid) is not None

        await pg.delete_character(cid)
        assert await pg.load_character(cid) is None

    async def test_save_character_overwrites_payload(self, pg: PostgresPersistence):
        """Re-saving the same id replaces the payload (upsert behaviour)."""
        cid = "char-003"
        await pg.save_character(cid, {"hp": 10})
        await pg.save_character(cid, {"hp": 99, "buff": "shield"})

        loaded = await pg.load_character(cid)
        assert loaded == {"hp": 99, "buff": "shield"}


@pytest.mark.asyncio
class TestSceneRoundtrip:
    async def test_save_and_load_scene(self, pg: PostgresPersistence):
        """Save a scene tied to a character; roundtrip the payload."""
        cid = "char-100"
        sid = "scene-001"
        scene_payload = {
            "title": "Moria Gate",
            "turn": 3,
            "npcs": ["gimli", "legolas"],
        }

        # FK requires the parent character to exist first.
        await pg.save_character(cid, {"name": "Gandalf"})
        await pg.save_scene(sid, cid, scene_payload)

        loaded = await pg.load_scene(sid)
        assert loaded is not None
        assert loaded == scene_payload

    async def test_save_scene_fk_violation_raises(self, pg: PostgresPersistence):
        """Saving a scene with non-existent character_id must raise IntegrityError.

        This guards the FK constraint declared on scenes.character_id:
        a child row cannot exist without its parent character. The adapter
        surfaces this as sqlalchemy.exc.IntegrityError (the dialect-neutral
        contract that works for both aiosqlite and asyncpg).
        """
        from sqlalchemy.exc import IntegrityError

        # Negative-control: parent does NOT exist (we never call save_character).
        # The adapter must refuse the orphan scene rather than silently insert.
        with pytest.raises(IntegrityError):
            await pg.save_scene("scene_99", "char_does_not_exist", {"foo": "bar"})


@pytest.mark.asyncio
class TestHealth:
    async def test_health_returns_true_after_init(self, pg: PostgresPersistence):
        """health() must return True once the adapter is usable, and
        must perform the lazy schema bootstrap along the way."""
        assert await pg.health() is True

        # And it should remain True on subsequent calls.
        assert await pg.health() is True
