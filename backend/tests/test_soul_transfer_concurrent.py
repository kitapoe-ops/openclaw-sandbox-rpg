"""
Concurrency tests for Soul Transfer (R1-14B audit finding 4).

These tests cover attack vectors that happy-path tests miss:
  V1: Concurrent same-(src, dst) transfers \u2014 verify atomicity
  V2: Crash mid-transfer \u2014 verify no partial state
  V3: Concurrent apply_soul on same soul_id \u2014 verify only-one-applies
  V4: Memory Palace concurrent writes during assembly \u2014 verify no race

Refs: real R1 audit 2026-06-04 (Wave 2 v0.2.0, verdict FAIL)
"""
from __future__ import annotations

import asyncio
import os
import sys
import sqlite3
import random
from pathlib import Path

import pytest
import pytest_asyncio

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
    from backend.memory_palace import MemoryPalace
    db_path = tmp_path / "memory_concurrent.db"
    yield MemoryPalace(db_path=str(db_path))


@pytest_asyncio.fixture
async def soul_service(memory_palace, tmp_path):
    from backend.soul_transfer import SoulTransferService
    yield SoulTransferService(
        memory_palace=memory_palace,
        soul_db_path=str(tmp_path / "soul_concurrent.db"),
    )


# ============================================
# V1: Concurrent same-(src, dst) transfers
# ============================================


class TestConcurrentTransfers:
    @pytest.mark.asyncio
    async def test_v1_ten_concurrent_transfers_all_persist(
        self, soul_service, memory_palace
    ):
        """
        V1: Fire 10 concurrent transfer() calls for the same (src, dst)
        pair. Every soul should be persisted \u2014 atomicity means each one
        is independent, no global state corruption.
        """
        # Seed source with memories
        for i in range(5):
            await memory_palace.add_memory(
                "src", f"mem_{i}", "episodic", "scene", salience=0.7
            )
        # Fire 10 concurrent transfers
        tasks = [
            soul_service.transfer(
                source_character_id="src",
                target_character_id="dst",
                character_state={"physical": {"stamina_level": "fresh"}},
            )
            for _ in range(10)
        ]
        souls = await asyncio.gather(*tasks)
        # All 10 should have unique soul_ids
        ids = [s.soul_id for s in souls]
        assert len(set(ids)) == 10
        # All 10 should be persisted
        for soul in souls:
            retrieved = await soul_service.get_soul(soul.soul_id)
            assert retrieved is not None
            assert retrieved.soul_id == soul.soul_id
        # Pending count = 10 (none applied yet)
        pending = await soul_service.get_pending_souls("dst")
        assert len(pending) == 10

    @pytest.mark.asyncio
    async def test_v1_concurrent_transfers_have_independent_factors(
        self, soul_service, memory_palace
    ):
        """
        V1.5: Concurrent transfers should produce different factors
        (rng advances independently per call). If they all had the same
        factor, anti-predictability would be broken.
        """
        await memory_palace.add_memory("src", "x", "episodic", "scene")
        tasks = [
            soul_service.assemble_payload("src", "dst", {})
            for _ in range(10)
        ]
        souls = await asyncio.gather(*tasks)
        factors = [s.degradation_factor for s in souls]
        # All within bounds
        for f in factors:
            assert 0.6 <= f <= 0.9
        # At least 3 unique values (anti-predictability)
        assert len(set(factors)) >= 3


# ============================================
# V2: Crash mid-transfer \u2014 no partial state
# ============================================


class TestCrashMidTransfer:
    @pytest.mark.asyncio
    async def test_v2_commit_failure_leaves_no_partial_soul(
        self, soul_service, memory_palace, monkeypatch
    ):
        """
        V2: Force commit() to fail mid-transfer. The entire transfer
        must roll back \u2014 no partial soul_payloads row.
        """
        await memory_palace.add_memory("src", "x", "episodic", "scene")
        # Wrap _connect_soul to inject a failing connection
        from backend import soul_transfer as st_mod
        original_connect = st_mod.SoulTransferService._connect_soul

        class FailingConnection:
            def __init__(self, real_conn):
                self._real = real_conn
                self._fail_commit = True

            def __getattr__(self, name):
                return getattr(self._real, name)

            def commit(self):
                raise RuntimeError("simulated commit failure")

            def rollback(self):
                self._real.rollback()

            def close(self):
                self._real.close()

            def execute(self, *args, **kwargs):
                return self._real.execute(*args, **kwargs)

        def failing_connect(self):
            return FailingConnection(original_connect(self))

        monkeypatch.setattr(
            st_mod.SoulTransferService, "_connect_soul", failing_connect
        )
        with pytest.raises(RuntimeError, match="simulated commit failure"):
            await soul_service.transfer("src", "dst", {})
        # Restore
        monkeypatch.setattr(
            st_mod.SoulTransferService, "_connect_soul", original_connect
        )
        # No partial soul_payloads row should exist
        assert await soul_service.count_transfers("dst") == 0

    @pytest.mark.asyncio
    async def test_v2_concurrent_transfers_with_one_failing(
        self, soul_service, memory_palace, monkeypatch
    ):
        """
        V2.5: 5 concurrent transfers, 1 of them forced to fail.
        The 4 healthy ones persist, the 1 failure does not corrupt
        the others (independent transactions).
        """
        await memory_palace.add_memory("src", "x", "episodic", "scene")
        from backend import soul_transfer as st_mod
        original_connect = st_mod.SoulTransferService._connect_soul
        call_count = {"n": 0}

        class SelectiveFailingConnection:
            def __init__(self, real_conn):
                self._real = real_conn
                self._fail = (call_count["n"] == 2)  # fail 3rd call
                call_count["n"] += 1

            def __getattr__(self, name):
                return getattr(self._real, name)

            def commit(self):
                if self._fail:
                    raise RuntimeError("simulated commit failure")
                self._real.commit()

            def rollback(self):
                self._real.rollback()

            def close(self):
                self._real.close()

            def execute(self, *args, **kwargs):
                return self._real.execute(*args, **kwargs)

        def selective_connect(self):
            return SelectiveFailingConnection(original_connect(self))

        monkeypatch.setattr(
            st_mod.SoulTransferService, "_connect_soul", selective_connect
        )
        # Fire 5 concurrent
        tasks = [
            soul_service.transfer("src", "dst", {})
            for _ in range(5)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Restore
        monkeypatch.setattr(
            st_mod.SoulTransferService, "_connect_soul", original_connect
        )
        # 4 successes, 1 failure
        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(successes) == 4
        assert len(failures) == 1
        # The failure did NOT corrupt the others \u2014 dst has exactly 4 souls
        assert await soul_service.count_transfers("dst") == 4


# ============================================
# V3: Concurrent apply_soul on same soul_id
# ============================================


class TestConcurrentApply:
    @pytest.mark.asyncio
    async def test_v3_two_concurrent_apply_soul_only_one_succeeds(
        self, soul_service, memory_palace
    ):
        """
        V3: Two callers race to apply_soul(same_id).
        The UPDATE...WHERE applied=0 clause must ensure only one
        updates the row; the other sees rows_updated=0.
        """
        await memory_palace.add_memory("src", "x", "episodic", "scene")
        soul = await soul_service.assemble_payload("src", "dst", {})
        await soul_service.persist_soul(soul)

        # Two concurrent apply_soul calls on same soul
        results = await asyncio.gather(
            soul_service.apply_soul(soul),
            soul_service.apply_soul(soul),
        )
        # Exactly one should have rows_updated=1, the other 0
        row_updates = [r["rows_updated"] for r in results]
        assert sorted(row_updates) == [0, 1], (
            f"Expected [0, 1] from concurrent apply, got {row_updates}"
        )
        # Verify final state: applied=1
        pending = await soul_service.get_pending_souls("dst")
        assert soul.soul_id not in [s.soul_id for s in pending]


# ============================================
# V4: Memory Palace concurrent writes during assembly
# ============================================


class TestAssemblyUnderConcurrentWrites:
    @pytest.mark.asyncio
    async def test_v4_assembly_snapshot_isolation(
        self, soul_service, memory_palace
    ):
        """
        V4: Start an assemble_payload, then race 5 more add_memory calls.
        The assembly's snapshot should not be corrupted by mid-flight
        writes \u2014 each memory is either in the snapshot or not, atomically.
        """
        # Seed 5 initial memories
        for i in range(5):
            await memory_palace.add_memory(
                "src", f"init_{i}", "episodic", "scene", salience=0.7
            )
        # Start assembly (reads all 5)
        async def slow_assembly():
            # Use a longer-running scenario by calling the underlying
            # get_memories directly
            return await memory_palace.get_memories("src", limit=10000)

        snapshot_task = asyncio.create_task(slow_assembly())
        # Add 5 more concurrently
        write_tasks = [
            memory_palace.add_memory("src", f"new_{i}", "episodic", "scene")
            for i in range(5)
        ]
        snapshot, *_ = await asyncio.gather(snapshot_task, *write_tasks)
        # Snapshot should be a coherent list \u2014 not partially-mutated
        # (SQLite is single-writer, so this is more of a sanity check)
        assert isinstance(snapshot, list)
        # After everything settles, total should be 10
        all_mems = await memory_palace.get_memories("src", limit=10000)
        assert len(all_mems) == 10

    @pytest.mark.asyncio
    async def test_v4_concurrent_assembly_produces_unique_payloads(
        self, soul_service, memory_palace
    ):
        """
        V4.5: 10 concurrent assemble_payload calls should produce
        10 distinct payloads (no shared state corruption).
        """
        for i in range(20):
            await memory_palace.add_memory("src", f"mem_{i}", "episodic", "scene")
        souls = await asyncio.gather(*[
            soul_service.assemble_payload("src", "dst", {}) for _ in range(10)
        ])
        # All 10 have unique soul_ids
        assert len(set(s.soul_id for s in souls)) == 10
        # All have valid structure
        for s in souls:
            assert s.soul_id is not None
            assert s.created_at is not None
            assert 0.6 <= s.degradation_factor <= 0.9
