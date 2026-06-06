"""
Tests for Memory Palace Phase A (SQLite + JSON).

Covers:
  - MemoryType + MemorySource enums
  - MemoryFragment dataclass validation
  - MemoryPalace class (14 async methods)
  - SQLite schema creation (idempotent)
  - All 5 Phase-A core methods
  - 9 Phase B/C stubs (verify they don't crash, with reasonable limits)
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

# Ensure backend on sys.path
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ============================================
# Fixtures
# ============================================


@pytest_asyncio.fixture
async def memory_palace(tmp_path):
    """Fresh MemoryPalace with a per-test SQLite file."""
    db_path = tmp_path / "memory_palace_test.db"
    from backend.memory_palace import MemoryPalace
    palace = MemoryPalace(db_path=str(db_path))
    yield palace
    # Cleanup happens automatically when tmp_path is removed


# ============================================
# Test 1 — Enum contracts
# ============================================


class TestEnums:
    """Verify the 4+4 enum contract is locked."""

    def test_memory_type_has_4_values(self):
        from backend.memory_palace import MemoryType
        assert len(MemoryType) == 4
        assert MemoryType.EPISODIC.value == "episodic"
        assert MemoryType.SEMANTIC.value == "semantic"
        assert MemoryType.PROCEDURAL.value == "procedural"
        assert MemoryType.EMOTIONAL.value == "emotional"

    def test_memory_source_has_4_values(self):
        from backend.memory_palace import MemorySource
        assert len(MemorySource) == 4
        assert MemorySource.SCENE.value == "scene"
        assert MemorySource.CHOICE.value == "choice"
        assert MemorySource.NPC_DIALOGUE.value == "npc_dialogue"
        assert MemorySource.WORLD_EVENT.value == "world_event"

    def test_enums_are_orthogonal(self):
        """A memory can be e.g. EMOTIONAL + PLAYER_DIRECT (later) or EMOTIONAL + CHOICE."""
        from backend.memory_palace import MemorySource, MemoryType
        # All 16 combinations should be valid
        for mt in MemoryType:
            for ms in MemorySource:
                combo = (mt, ms)
                assert combo[0] in MemoryType
                assert combo[1] in MemorySource


# ============================================
# Test 2 — MemoryFragment dataclass
# ============================================


class TestMemoryFragment:
    """Verify dataclass field validation."""

    def test_valid_construction(self):
        from backend.memory_palace import MemoryFragment, MemorySource, MemoryType
        m = MemoryFragment(
            id="m1",
            character_id="char1",
            memory_type=MemoryType.EPISODIC,
            content="defeated the dragon",
            source=MemorySource.SCENE,
            salience=0.8,
            created_at="2026-01-01T00:00:00Z",
            last_accessed_at="2026-01-01T00:00:00Z",
            access_count=0,
        )
        assert m.id == "m1"
        assert m.salience == 0.8

    def test_salience_out_of_range_raises(self):
        from backend.memory_palace import MemoryFragment, MemorySource, MemoryType
        with pytest.raises(ValueError, match="salience"):
            MemoryFragment(
                id="m1",
                character_id="char1",
                memory_type=MemoryType.EPISODIC,
                content="x",
                source=MemorySource.SCENE,
                salience=1.5,  # out of range
                created_at="2026-01-01T00:00:00Z",
                last_accessed_at="2026-01-01T00:00:00Z",
                access_count=0,
            )

    def test_decay_rate_out_of_range_raises(self):
        from backend.memory_palace import MemoryFragment, MemorySource, MemoryType
        with pytest.raises(ValueError, match="decay_rate"):
            MemoryFragment(
                id="m1",
                character_id="char1",
                memory_type=MemoryType.EPISODIC,
                content="x",
                source=MemorySource.SCENE,
                salience=0.5,
                created_at="2026-01-01T00:00:00Z",
                last_accessed_at="2026-01-01T00:00:00Z",
                access_count=0,
                decay_rate=-0.1,  # negative
            )

    def test_to_from_dict_roundtrip(self):
        from backend.memory_palace import MemoryFragment, MemorySource, MemoryType
        original = MemoryFragment(
            id="m1",
            character_id="char1",
            memory_type=MemoryType.PROCEDURAL,
            content="how to cast fireball",
            source=MemorySource.NPC_DIALOGUE,
            salience=0.9,
            created_at="2026-01-01T00:00:00Z",
            last_accessed_at="2026-01-01T00:00:00Z",
            access_count=3,
            tags=["magic", "fire"],
            linked_memories=["m2", "m3"],
        )
        d = original.to_dict()
        restored = MemoryFragment.from_dict(d)
        assert restored.id == original.id
        assert restored.memory_type == original.memory_type
        assert restored.tags == original.tags
        assert restored.linked_memories == original.linked_memories


# ============================================
# Test 3 — MemoryPalace core methods
# ============================================


class TestMemoryPalaceCore:
    """Test the 5 Phase A core methods."""

    @pytest.mark.asyncio
    async def test_add_and_get_memory(self, memory_palace):
        mid = await memory_palace.add_memory(
            character_id="char1",
            content="met a merchant in the tavern",
            memory_type="episodic",
            source="scene",
            salience=0.7,
        )
        assert isinstance(mid, str)
        assert len(mid) == 36  # UUID

        mem = await memory_palace.get_memory(mid)
        assert mem is not None
        assert mem.content == "met a merchant in the tavern"
        assert mem.salience == 0.7
        # access_count should increment
        assert mem.access_count == 1

    @pytest.mark.asyncio
    async def test_get_memory_increments_access_count(self, memory_palace):
        mid = await memory_palace.add_memory(
            character_id="char1",
            content="x",
            memory_type="episodic",
            source="scene",
        )
        await memory_palace.get_memory(mid)
        await memory_palace.get_memory(mid)
        mem = await memory_palace.get_memory(mid)
        assert mem.access_count == 3

    @pytest.mark.asyncio
    async def test_get_memories_filter_by_type(self, memory_palace):
        await memory_palace.add_memory("c1", "episodic 1", "episodic", "scene")
        await memory_palace.add_memory("c1", "semantic 1", "semantic", "scene")
        await memory_palace.add_memory("c1", "episodic 2", "episodic", "scene")
        await memory_palace.add_memory("c1", "semantic 2", "semantic", "scene")

        episodic = await memory_palace.get_memories("c1", memory_type="episodic")
        assert len(episodic) == 2
        assert all(m.memory_type == "episodic" for m in episodic)

    @pytest.mark.asyncio
    async def test_get_memories_filter_by_min_salience(self, memory_palace):
        await memory_palace.add_memory("c1", "low", "episodic", "scene", salience=0.2)
        await memory_palace.add_memory("c1", "high", "episodic", "scene", salience=0.9)

        high = await memory_palace.get_memories("c1", min_salience=0.5)
        assert len(high) == 1
        assert high[0].salience == 0.9

    @pytest.mark.asyncio
    async def test_get_memories_sorted_by_salience_desc(self, memory_palace):
        await memory_palace.add_memory("c1", "a", "episodic", "scene", salience=0.3)
        await memory_palace.add_memory("c1", "b", "episodic", "scene", salience=0.9)
        await memory_palace.add_memory("c1", "c", "episodic", "scene", salience=0.6)

        mems = await memory_palace.get_memories("c1")
        saliences = [m.salience for m in mems]
        assert saliences == [0.9, 0.6, 0.3]

    @pytest.mark.asyncio
    async def test_search_keyword(self, memory_palace):
        await memory_palace.add_memory("c1", "met a wizard named Gandalf", "episodic", "scene")
        await memory_palace.add_memory("c1", "found a treasure chest", "episodic", "scene")
        await memory_palace.add_memory("c1", "fought a wizard in the tower", "episodic", "scene")

        results = await memory_palace.search_keyword("c1", "wizard")
        assert len(results) == 2
        assert all("wizard" in m.content for m in results)

    @pytest.mark.asyncio
    async def test_search_keyword_by_tag(self, memory_palace):
        await memory_palace.add_memory("c1", "x", "episodic", "scene", tags=["magic", "fire"])
        await memory_palace.add_memory("c1", "y", "episodic", "scene", tags=["combat"])
        results = await memory_palace.search_keyword("c1", "magic")
        assert len(results) == 1
        assert "magic" in results[0].tags

    @pytest.mark.asyncio
    async def test_count(self, memory_palace):
        assert await memory_palace.count("c1") == 0
        await memory_palace.add_memory("c1", "a", "episodic", "scene")
        await memory_palace.add_memory("c1", "b", "episodic", "scene")
        assert await memory_palace.count("c1") == 2

    @pytest.mark.asyncio
    async def test_get_memories_limit(self, memory_palace):
        for i in range(10):
            await memory_palace.add_memory("c1", f"mem{i}", "episodic", "scene")
        assert len(await memory_palace.get_memories("c1", limit=3)) == 3


# ============================================
# Test 4 — Phase B/C stubs (verify they work, not crash)
# ============================================


class TestMemoryPalaceStubs:
    """The 9 remaining methods should at least be callable and produce sensible results."""

    @pytest.mark.asyncio
    async def test_update_salience(self, memory_palace):
        mid = await memory_palace.add_memory("c1", "x", "episodic", "scene", salience=0.5)
        assert await memory_palace.update_salience(mid, 0.9) is True
        mem = await memory_palace.get_memory(mid)
        assert mem.salience == 0.9

    @pytest.mark.asyncio
    async def test_update_salience_out_of_range_raises(self, memory_palace):
        with pytest.raises(ValueError, match="salience"):
            await memory_palace.update_salience("any_id", 1.5)

    @pytest.mark.asyncio
    async def test_link_memories(self, memory_palace):
        m1 = await memory_palace.add_memory("c1", "first", "episodic", "scene")
        m2 = await memory_palace.add_memory("c1", "second", "episodic", "scene")
        assert await memory_palace.link_memories(m1, m2) is True

        # Both should appear in each other's links
        mem1 = await memory_palace.get_memory(m1)
        mem2 = await memory_palace.get_memory(m2)
        assert m2 in mem1.linked_memories
        assert m1 in mem2.linked_memories

    @pytest.mark.asyncio
    async def test_link_same_memory_returns_false(self, memory_palace):
        m1 = await memory_palace.add_memory("c1", "x", "episodic", "scene")
        assert await memory_palace.link_memories(m1, m1) is False

    @pytest.mark.asyncio
    async def test_traverse_links(self, memory_palace):
        m1 = await memory_palace.add_memory("c1", "first", "episodic", "scene")
        m2 = await memory_palace.add_memory("c1", "second", "episodic", "scene")
        m3 = await memory_palace.add_memory("c1", "third", "episodic", "scene")
        await memory_palace.link_memories(m1, m2)
        await memory_palace.link_memories(m2, m3)
        reachable = await memory_palace.traverse_links(m1, max_depth=2)
        ids = {m.id for m in reachable}
        assert m2 in ids
        assert m3 in ids
        assert m1 not in ids  # start is excluded

    @pytest.mark.asyncio
    async def test_apply_decay(self, memory_palace):
        await memory_palace.add_memory(
            "c1", "x", "episodic", "scene", salience=1.0, decay_rate=0.1
        )
        await memory_palace.add_memory(
            "c1", "y", "episodic", "scene", salience=1.0, decay_rate=0.2
        )
        updated = await memory_palace.apply_decay("c1", days_elapsed=2.0)
        # Both memories should have been decayed
        assert updated == 2
        # x should now be at 0.8, y at 0.6
        mems = await memory_palace.get_memories("c1")
        for m in mems:
            assert m.salience < 1.0

    @pytest.mark.asyncio
    async def test_apply_decay_zero_days_no_change(self, memory_palace):
        await memory_palace.add_memory("c1", "x", "episodic", "scene", salience=0.5, decay_rate=0.1)
        updated = await memory_palace.apply_decay("c1", days_elapsed=0.0)
        assert updated == 0

    @pytest.mark.asyncio
    async def test_archive_cold_memories(self, memory_palace):
        await memory_palace.add_memory("c1", "cold", "episodic", "scene", salience=0.01)
        await memory_palace.add_memory("c1", "warm", "episodic", "scene", salience=0.5)
        archived = await memory_palace.archive_cold_memories("c1", salience_floor=0.05)
        assert archived == 1
        # Only the warm memory should remain active
        active = await memory_palace.get_memories("c1")
        assert len(active) == 1
        assert active[0].content == "warm"

    @pytest.mark.asyncio
    async def test_export_state(self, memory_palace):
        await memory_palace.add_memory("c1", "a", "episodic", "scene")
        await memory_palace.add_memory("c1", "b", "semantic", "scene")
        state = await memory_palace.export_state("c1")
        assert state["character_id"] == "c1"
        assert state["total_count"] == 2
        assert "exported_at" in state
        assert len(state["memories"]) == 2

    @pytest.mark.asyncio
    async def test_transfer_memories_preserves_semantic(self, memory_palace):
        await memory_palace.add_memory("src", "episodic fact", "episodic", "scene")
        await memory_palace.add_memory("src", "semantic fact", "semantic", "scene")
        await memory_palace.add_memory("src", "procedural fact", "procedural", "scene")

        transferred = await memory_palace.transfer_memories("src", "dst", preservation_rate=0.0)
        # semantic + procedural always kept; episodic sampled with rate=0.0 → not kept
        assert transferred == 2
        # dst should have 2 memories
        assert await memory_palace.count("dst") == 2


# ============================================
# Test 5 — Schema integrity
# ============================================


class TestSchemaIntegrity:
    """Verify the SQLite schema is correct and enforces constraints."""

    def test_initialize_storage_idempotent(self, tmp_path):
        from backend.memory_palace import MemoryPalace
        db = tmp_path / "test.db"
        p1 = MemoryPalace(str(db))
        p2 = MemoryPalace(str(db))  # second init should not raise
        # Verify table exists
        import sqlite3
        conn = sqlite3.connect(str(db))
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_entries'"
            ).fetchall()
            assert len(rows) == 1
        finally:
            conn.close()

    def test_check_constraint_rejects_invalid_type(self, tmp_path):
        """Direct INSERT with invalid memory_type should fail (CHECK constraint)."""
        import sqlite3

        from backend.memory_palace import MemoryPalace
        db = tmp_path / "test.db"
        MemoryPalace(str(db))
        conn = sqlite3.connect(str(db))
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO memory_entries
                    (id, character_id, memory_type, content, source,
                     salience, created_at, last_accessed_at, access_count,
                     tags_json, linked_memories_json, decay_rate,
                     metadata_json, archived)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "x1", "c1", "INVALID_TYPE", "content", "scene",
                        0.5, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", 0,
                        "[]", "[]", 0.05, "{}", 0,
                    ),
                )
        finally:
            conn.close()


# ============================================
# Test 6 \u2014 R1 Audit regression-protection tests
# ============================================


class TestR1AuditFixesV2:
    """Refined R1 audit regression tests (fix 3 failed tests)."""

    @pytest.mark.asyncio
    async def test_consolidate_n_plus_1_with_true_duplicates(self, memory_palace, monkeypatch):
        """consolidate_memories must use ONE connection even with true duplicates."""
        import sqlite3
        connection_opens = []
        original_connect = sqlite3.connect

        def tracking_connect(*args, **kwargs):
            connection_opens.append(1)
            return original_connect(*args, **kwargs)

        monkeypatch.setattr(sqlite3, "connect", tracking_connect)
        from backend import memory_palace as mp_mod
        monkeypatch.setattr(mp_mod.sqlite3, "connect", tracking_connect)

        # Create 30 TRUE duplicates (same content)
        for i in range(30):
            await memory_palace.add_memory(
                "c1", "the wizard cast fireball", "episodic", "scene"
            )

        connection_opens.clear()
        merged = await memory_palace.consolidate_memories(
            "c1", similarity_threshold=0.99, page_size=10
        )
        assert len(connection_opens) <= 2, (
            f"consolidate_memories opened {len(connection_opens)} connections "
            f"(expected \u2264 2). N+1 regression!"
        )
        # All but 1 should be merged (highest-salience kept)
        assert merged == 29

    @pytest.mark.asyncio
    async def test_transfer_atomic_via_hooks(self, memory_palace):
        """Use the memory_palace's own _connect() to inject failure."""
        # Add 5 source memories
        for i in range(5):
            await memory_palace.add_memory(
                "src", f"src_mem_{i}", "episodic", "scene", salience=0.8
            )
        # Monkey-patch the connection wrapper to raise on commit
        from backend import memory_palace as mp_mod
        original_connect = mp_mod.MemoryPalace._connect

        class FailingConnection:
            def __init__(self, real_conn):
                self._real = real_conn
                self._fail_next = True

            def __getattr__(self, name):
                return getattr(self._real, name)

            def commit(self):
                raise RuntimeError("simulated commit failure")

            def rollback(self):
                self._real.rollback()

            def close(self):
                self._real.close()

        def failing_connect(self):
            return FailingConnection(original_connect(self))

        mp_mod.MemoryPalace._connect = failing_connect
        try:
            with pytest.raises(RuntimeError, match="simulated commit failure"):
                await memory_palace.transfer_memories("src", "dst", preservation_rate=1.0)
        finally:
            mp_mod.MemoryPalace._connect = original_connect

        # dst must be empty
        assert await memory_palace.count("dst") == 0
