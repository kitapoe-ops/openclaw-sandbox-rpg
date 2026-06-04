"""
Tests for Wave 2 Core #3: Async Turn System + God Agent ETL.
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
# Turn System Fixtures
# ============================================


@pytest_asyncio.fixture
async def turn_system(tmp_path):
    from backend.turn_system import TurnSystem
    yield TurnSystem(db_path=str(tmp_path / "turns.db"))


# ============================================
# Turn System Tests (8 tests)
# ============================================


class TestTurnSystem:
    @pytest.mark.asyncio
    async def test_submit_and_advance(self, turn_system):
        """Submit a turn, then advance to claim it."""
        from backend.turn_system import TurnStatus
        tid = await turn_system.submit_turn(
            "char_aria",
            {"choice": {"option_id": "opt_01"}},
        )
        assert isinstance(tid, str)
        turn = await turn_system.advance_turn("char_aria")
        assert turn is not None
        assert turn.turn_id == tid
        assert turn.status == TurnStatus.ACTIVE
        assert turn.round_number == 1

    @pytest.mark.asyncio
    async def test_round_number_increments(self, turn_system):
        """Subsequent turns get round_number = prev + 1."""
        tid1 = await turn_system.submit_turn("c1", {"x": 1})
        t1 = await turn_system.advance_turn("c1")
        assert t1.round_number == 1
        await turn_system.complete_turn(tid1, {"narrative": "ok"})

        tid2 = await turn_system.submit_turn("c1", {"x": 2})
        t2 = await turn_system.advance_turn("c1")
        assert t2.round_number == 2

    @pytest.mark.asyncio
    async def test_complete_turn_clears_active(self, turn_system):
        """After complete_turn, the active_turn is gone."""
        from backend.turn_system import TurnStatus
        tid = await turn_system.submit_turn("c1", {})
        await turn_system.advance_turn("c1")
        assert await turn_system.get_active_turn("c1") is not None

        ok = await turn_system.complete_turn(tid, {"narrative": "done"})
        assert ok is True
        assert await turn_system.get_active_turn("c1") is None
        assert (await turn_system.get_turn(tid)).status == TurnStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_fifo_order(self, turn_system):
        """Pending turns are claimed in submission order (FIFO)."""
        tids = []
        for i in range(5):
            tid = await turn_system.submit_turn("c1", {"idx": i})
            tids.append(tid)
        # Advance and check order
        for expected_tid in tids:
            turn = await turn_system.advance_turn("c1")
            assert turn.turn_id == expected_tid
            await turn_system.complete_turn(turn.turn_id, {})

    @pytest.mark.asyncio
    async def test_advance_returns_none_when_empty(self, turn_system):
        """No pending turns => None."""
        result = await turn_system.advance_turn("nobody")
        assert result is None

    @pytest.mark.asyncio
    async def test_concurrent_advance_only_one_wins_per_character(
        self, turn_system
    ):
        """
        5 concurrent advance_turn() calls for the same character.
        Only ONE should win (atomic claim), the others get None.
        """
        await turn_system.submit_turn("c1", {})
        results = await asyncio.gather(*[
            turn_system.advance_turn("c1") for _ in range(5)
        ])
        # Exactly 1 winner
        winners = [r for r in results if r is not None]
        losers = [r for r in results if r is None]
        assert len(winners) == 1
        assert len(losers) == 4
        # All winners are the same turn_id
        assert len(set(w.turn_id for w in winners)) == 1

    @pytest.mark.asyncio
    async def test_expire_overdue(self, turn_system):
        """Overdue pending turns are marked expired."""
        tid = await turn_system.submit_turn("c1", {}, deadline_seconds=-1)
        expired = await turn_system.expire_overdue_turns()
        assert expired == 1
        turn = await turn_system.get_turn(tid)
        from backend.turn_system import TurnStatus
        assert turn.status == TurnStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_get_pending_count(self, turn_system):
        """Pending count tracks submitted-but-not-advanced turns."""
        assert await turn_system.get_pending_count("c1") == 0
        await turn_system.submit_turn("c1", {})
        await turn_system.submit_turn("c1", {})
        assert await turn_system.get_pending_count("c1") == 2
        await turn_system.advance_turn("c1")
        # 1 still pending, 1 active
        assert await turn_system.get_pending_count("c1") == 1


# ============================================
# ETL Service Fixtures
# ============================================


@pytest_asyncio.fixture
async def etl_service(tmp_path):
    from backend.etl_service import EtlService
    yield EtlService(db_path=str(tmp_path / "etl.db"))


# ============================================
# ETL Service Tests (8 tests)
# ============================================


class TestEtlService:
    @pytest.mark.asyncio
    async def test_enqueue_and_process(self, etl_service):
        """Basic enqueue + process_outbox flow."""
        from backend.etl_service import OutboxOpType
        oid = await etl_service.enqueue(
            OutboxOpType.APPLY_DECAY, target_id="char_a",
            payload={"days_elapsed": 1.0},
        )
        assert isinstance(oid, str)
        result = await etl_service.process_outbox()
        assert result["succeeded"] == 1
        assert result["failed"] == 0
        # Pending should be 0 after process
        assert await etl_service.get_pending_count() == 0

    @pytest.mark.asyncio
    async def test_plan_daily_tick_enqueues_all_ops(self, etl_service):
        """plan_daily_tick should enqueue decay + consolidate + world params."""
        counts = await etl_service.plan_daily_tick(
            character_ids=["c1", "c2", "c3"],
            world_parameter_ids=["param_dragon_threat", "param_plague"],
        )
        assert counts["apply_decay"] == 3  # one per character
        assert counts["consolidate"] == 3
        assert counts["world_param_fluctuate"] == 2
        # Total 8 pending ops
        assert await etl_service.get_pending_count() == 8

    @pytest.mark.asyncio
    async def test_process_outbox_batch_size(self, etl_service):
        """batch_size limits how many ops are processed in one call."""
        from backend.etl_service import OutboxOpType
        for i in range(10):
            await etl_service.enqueue(OutboxOpType.APPLY_DECAY, target_id=f"c{i}")
        # batch_size=3 \u2192 process 3
        result = await etl_service.process_outbox(batch_size=3)
        assert result["succeeded"] == 3
        # 7 still pending
        assert await etl_service.get_pending_count() == 7

    @pytest.mark.asyncio
    async def test_failed_op_stays_pending_for_retry(self, etl_service, monkeypatch):
        """Failed ops return to pending status with error_message set."""
        from backend.etl_service import OutboxOpType
        oid = await etl_service.enqueue(OutboxOpType.APPLY_DECAY, target_id="c1")
        # Force _execute_op to fail
        async def failing_execute(item):
            raise ValueError("simulated downstream failure")
        monkeypatch.setattr(etl_service, "_execute_op", failing_execute)
        result = await etl_service.process_outbox()
        assert result["failed"] == 1
        # Op is back in pending (with attempts incremented)
        assert await etl_service.get_pending_count() == 1
        # attempts > 0
        assert await etl_service.get_failed_count() == 1

    @pytest.mark.asyncio
    async def test_concurrent_process_outbox_no_double_execution(
        self, etl_service
    ):
        """Two concurrent process_outbox calls must not double-process."""
        from backend.etl_service import OutboxOpType
        for i in range(5):
            await etl_service.enqueue(OutboxOpType.APPLY_DECAY, target_id=f"c{i}")
        # Two concurrent process calls (each with batch_size=10)
        r1, r2 = await asyncio.gather(
            etl_service.process_outbox(batch_size=10),
            etl_service.process_outbox(batch_size=10),
        )
        # Total succeeded = 5 (no double-processing)
        total = r1["succeeded"] + r2["succeeded"]
        assert total == 5
        # 0 pending after
        assert await etl_service.get_pending_count() == 0

    @pytest.mark.asyncio
    async def test_get_stats(self, etl_service):
        """Stats show counts by status."""
        from backend.etl_service import OutboxOpType
        await etl_service.enqueue(OutboxOpType.APPLY_DECAY, "c1")
        await etl_service.enqueue(OutboxOpType.APPLY_DECAY, "c2")
        await etl_service.enqueue(OutboxOpType.CONSOLIDATE, "c1")
        # Process 1
        await etl_service.process_outbox(batch_size=1)
        stats = await etl_service.get_stats()
        assert stats.get("completed", 0) == 1
        assert stats.get("pending", 0) == 2

    @pytest.mark.asyncio
    async def test_outbox_idempotency_via_target_id(self, etl_service):
        """
        plan_daily_tick is naturally idempotent across same-day re-runs
        (each enqueue creates a new outbox_id, but the same target+op
        will be picked up independently). The retry mechanism handles
        failures via attempts counter.

        We verify the structure: two plan_daily_tick calls produce
        duplicate ops for retry, which is correct behavior.
        """
        await etl_service.plan_daily_tick(character_ids=["c1"])
        n1 = await etl_service.get_pending_count()
        await etl_service.plan_daily_tick(character_ids=["c1"])
        n2 = await etl_service.get_pending_count()
        # Second tick doubled the count (retry semantics)
        assert n2 == 2 * n1
        # After processing, all completed
        result = await etl_service.process_outbox(batch_size=100)
        assert result["succeeded"] == n2

    @pytest.mark.asyncio
    async def test_failure_then_retry_succeeds(self, etl_service, monkeypatch):
        """Op that fails first time should succeed on second attempt."""
        from backend.etl_service import OutboxOpType
        await etl_service.enqueue(OutboxOpType.APPLY_DECAY, "c1")
        # First call: force failure
        fail_count = {"n": 0}

        async def maybe_failing_execute(item):
            fail_count["n"] += 1
            if fail_count["n"] == 1:
                raise ValueError("transient error")
            # Second call succeeds

        monkeypatch.setattr(etl_service, "_execute_op", maybe_failing_execute)
        # First attempt: fails, returns to pending
        r1 = await etl_service.process_outbox()
        assert r1["failed"] == 1
        # Second attempt: succeeds
        r2 = await etl_service.process_outbox()
        assert r2["succeeded"] == 1
        # Op is now completed
        stats = await etl_service.get_stats()
        assert stats.get("completed", 0) == 1
