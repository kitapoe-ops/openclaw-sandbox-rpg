"""
Tests for backend/audit_queue.py — Phase E8 Async Audit Queue.

These tests are network-free: they pass an AsyncMock as the R1
client, so no LM Studio call is made. The module-level singleton
is reset between tests via the `audit_queue_fixture` autouse
fixture.

Covered (10/10):
    1.  submit() returns a uuid-like string
    2.  get_result() returns an AuditResult with a terminal verdict
    3.  Zero workers queue: items stay PENDING (no worker drain)
    4.  Multiple workers process in parallel (2x faster than serial)
    5.  Backpressure blocks submit() when queue is full (BLOCK policy)
    6.  health() reports correct counts after a few audits
    7.  Per-request timeout marks the result TIMEOUT
    8.  R1 client exception marks the result ERROR
    9.  get_status() is non-blocking even when audit is in flight
    10. stop(drain=False) cancels workers cleanly

Frozen-file rule
----------------
The tests import only from `backend.audit_queue` and stdlib. They
do NOT import from any frozen file (turn_system, r1_audit_client,
action.py, etc.).
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure repo root on sys.path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.audit_queue import (  # noqa: E402
    AsyncAuditQueue,
    AuditRequest,
    AuditResult,
    AuditVerdict,
    BackpressurePolicy,
    audit_queue,
    get_audit_queue,
    reset_audit_queue,
)

# ============================================
# Fixtures
# ============================================


@pytest.fixture(autouse=True)
def reset_singleton():
    """Each test starts with a fresh module-level singleton."""
    reset_audit_queue()
    yield
    reset_audit_queue()


def _make_mock_r1(
    *,
    delay: float = 0.0,
    verdict: str = "PASS",
    findings: list[dict[str, Any]] | None = None,
    raise_exc: BaseException | None = None,
) -> AsyncMock:
    """Build an AsyncMock standing in for R1AuditClient.

    `delay`: seconds to sleep before returning, to simulate R1 slowness.
    `verdict` / `findings`: shape of the dict the mock returns.
    `raise_exc`: if set, the mock raises this exception instead.
    """
    mock = AsyncMock()

    async def _audit(target_files, concerns, context=None):
        if raise_exc is not None:
            raise raise_exc
        if delay > 0:
            await asyncio.sleep(delay)
        return {
            "verdict": verdict,
            "findings": findings or [],
            "raw_response": f"mock-r1: {verdict}",
        }

    mock.audit.side_effect = _audit
    return mock


def _make_request() -> AuditRequest:
    return AuditRequest(
        target_files=["backend/audit_queue.py"],
        concerns=["does the queue work?"],
    )


# ============================================
# 1. submit() returns a uuid-like string
# ============================================


@pytest.mark.asyncio
async def test_submit_returns_request_id():
    """submit() returns a non-empty uuid-shaped string and a PENDING
    result is recorded in the result map."""
    r1 = _make_mock_r1()
    q = AsyncAuditQueue(r1_client=r1)
    await q.start()

    rid = await q.submit(_make_request())
    try:
        # uuid.UUID() raises if not a valid uuid
        uuid.UUID(rid)
    except ValueError:
        pytest.fail(f"submit() returned a non-uuid string: {rid!r}")

    # The result should be registered as PENDING
    assert q.get_status(rid) == AuditVerdict.PENDING

    await q.stop()


# ============================================
# 2. get_result() returns a terminal AuditResult
# ============================================


@pytest.mark.asyncio
async def test_get_result_returns_audit_result():
    """After a real R1 response, get_result() returns a terminal
    AuditResult with verdict + findings populated."""
    r1 = _make_mock_r1(
        verdict="CONDITIONAL",
        findings=[{"severity": "LOW", "issue": "x", "evidence": "y", "recommendation": "z"}],
    )
    q = AsyncAuditQueue(r1_client=r1, worker_count=1)
    await q.start()

    rid = await q.submit(_make_request())
    result = await q.get_result(rid, timeout=2.0)

    assert result.request_id == rid
    assert result.verdict == AuditVerdict.CONDITIONAL
    assert len(result.findings) == 1
    assert result.findings[0]["issue"] == "x"
    assert result.completed_at > 0
    assert result.duration_seconds >= 0

    await q.stop()


# ============================================
# 3. Zero workers: items stay PENDING
# ============================================


@pytest.mark.asyncio
async def test_zero_workers_does_not_process():
    """If we DON'T start workers (or start with 0), submitted items
    stay PENDING forever — no background drain."""
    r1 = _make_mock_r1()
    q = AsyncAuditQueue(r1_client=r1, worker_count=1)
    # NOTE: deliberately NOT calling q.start()

    rid = await q.submit(_make_request())
    # Wait a bit to be sure no worker picked it up
    await asyncio.sleep(0.1)
    assert q.get_status(rid) == AuditVerdict.PENDING

    # start() and stop() should still work cleanly
    await q.start()
    await q.stop()


# ============================================
# 4. Multiple workers process in parallel
# ============================================


@pytest.mark.asyncio
async def test_workers_process_in_parallel():
    """With worker_count=3 and 3 slow audits, total wall-clock time
    should be ~1x the per-audit delay (parallelism), NOT 3x (serial)."""
    per_audit_delay = 0.30
    r1 = _make_mock_r1(delay=per_audit_delay)
    q = AsyncAuditQueue(r1_client=r1, worker_count=3, max_queue_size=10)
    await q.start()

    rids = []
    t0 = time.monotonic()
    for _ in range(3):
        rids.append(await q.submit(_make_request()))

    for rid in rids:
        result = await q.get_result(rid, timeout=2.0)
        assert result.verdict == AuditVerdict.PASS
    elapsed = time.monotonic() - t0

    # If serial: ~0.9s. If parallel: ~0.3s + scheduling overhead.
    # Allow 0.6s as the parallel-bound (2x the single delay).
    serial_lower_bound = 2 * per_audit_delay  # 0.6s
    assert elapsed < serial_lower_bound, (
        f"workers did not run in parallel; elapsed={elapsed:.2f}s, "
        f"expected < {serial_lower_bound:.2f}s"
    )

    await q.stop()


# ============================================
# 5. Backpressure BLOCK: submit blocks when queue is full
# ============================================


@pytest.mark.asyncio
async def test_backpressure_blocks_when_queue_full():
    """With max_queue_size=2 and a slow worker, the 4th submit()
    call should block (not return immediately) until the worker
    drains the first item.

    Note: maxsize=2 means the queue blocks on put ONLY when it
    already holds 2 items. So we need 1 in-flight (worker) + 2
    queued = 3rd queued, and the 4th submit is the one that
    actually blocks.
    """
    # Slow enough that the worker cannot drain before our 4th submit.
    per_audit = 0.30
    r1 = _make_mock_r1(delay=per_audit)
    q = AsyncAuditQueue(
        r1_client=r1,
        worker_count=1,
        max_queue_size=2,
        backpressure=BackpressurePolicy.BLOCK,
    )
    await q.start()

    # rid1: worker picks it up immediately. In-flight: 1, queue: 0.
    rid1 = await q.submit(_make_request())
    # rid2: queue: 1, in-flight: 1.
    rid2 = await q.submit(_make_request())
    # rid3: queue: 2 (full). put() returns immediately because we
    # were putting to a not-yet-full queue; the queue is now full.
    rid3 = await q.submit(_make_request())

    # rid4: must block until the worker finishes rid1.
    t0 = time.monotonic()
    rid4 = await q.submit(_make_request())
    blocked_time = time.monotonic() - t0

    # It had to wait ~per_audit for the worker to free a slot.
    # Allow some scheduling slack; assert it is at least half the delay.
    assert blocked_time >= per_audit * 0.4, (
        f"submit() did not block on full queue; blocked_time={blocked_time:.3f}s, "
        f"expected >= {per_audit * 0.4:.3f}s"
    )
    assert len({rid1, rid2, rid3, rid4}) == 4

    # Cleanup
    for rid in (rid1, rid2, rid3, rid4):
        await q.get_result(rid, timeout=5.0)
    await q.stop()


# ============================================
# 5b. Backpressure FAIL_FAST: submit raises QueueFull
# ============================================


@pytest.mark.asyncio
async def test_backpressure_fail_fast_raises():
    """With FAIL_FAST, submitting to a full queue raises immediately."""
    r1 = _make_mock_r1(delay=10.0)  # never finishes
    q = AsyncAuditQueue(
        r1_client=r1,
        worker_count=1,
        max_queue_size=1,
        backpressure=BackpressurePolicy.FAIL_FAST,
    )
    await q.start()

    await q.submit(_make_request())
    with pytest.raises(asyncio.QueueFull):
        await q.submit(_make_request())

    # Don't bother waiting for the slow worker; cancel
    await q.stop(drain=False)


# ============================================
# 6. health() reports correct counts
# ============================================


@pytest.mark.asyncio
async def test_health_reports_stats():
    """After submitting and completing 2 audits, health() shows
    the right submitted/completed/queue_depth numbers."""
    r1 = _make_mock_r1(verdict="PASS")
    q = AsyncAuditQueue(r1_client=r1, worker_count=2, max_queue_size=20)
    await q.start()

    rid_a = await q.submit(_make_request())
    rid_b = await q.submit(_make_request())
    await q.get_result(rid_a, timeout=2.0)
    await q.get_result(rid_b, timeout=2.0)

    h = q.health()
    assert h["running"] is True
    assert h["worker_count"] == 2
    assert h["max_queue_size"] == 20
    assert h["backpressure"] == "block"
    assert h["submitted"] == 2
    assert h["completed"] == 2
    assert h["errored"] == 0
    assert h["timed_out"] == 0
    assert h["queue_depth"] == 0
    assert h["tracked_results"] == 2
    assert h["verdict_breakdown"].get("pass", 0) == 2

    await q.stop()


# ============================================
# 7. Timeout marks the result as TIMEOUT
# ============================================


@pytest.mark.asyncio
async def test_timeout_marks_result_as_timeout():
    """If R1 sleeps longer than request_timeout, the worker marks
    the result TIMEOUT (does NOT raise into the worker)."""
    r1 = _make_mock_r1(delay=0.50)  # exceeds timeout=0.10
    q = AsyncAuditQueue(
        r1_client=r1,
        worker_count=1,
        request_timeout=0.10,
    )
    await q.start()

    rid = await q.submit(_make_request())
    result = await q.get_result(rid, timeout=2.0)

    assert result.verdict == AuditVerdict.TIMEOUT
    assert "exceeded" in (result.error or "")
    assert q.health()["timed_out"] == 1

    # Worker must still be alive — submit another, it should also time out
    rid2 = await q.submit(_make_request())
    result2 = await q.get_result(rid2, timeout=2.0)
    assert result2.verdict == AuditVerdict.TIMEOUT

    await q.stop()


# ============================================
# 8. R1 client exception marks the result as ERROR
# ============================================


@pytest.mark.asyncio
async def test_audit_failure_marks_result_as_error():
    """If the R1 client raises (network error, JSON parse, etc.),
    the result is ERROR, not lost."""
    r1 = _make_mock_r1(raise_exc=RuntimeError("LM Studio disconnected"))
    q = AsyncAuditQueue(r1_client=r1, worker_count=1)
    await q.start()

    rid = await q.submit(_make_request())
    result = await q.get_result(rid, timeout=2.0)

    assert result.verdict == AuditVerdict.ERROR
    assert "RuntimeError" in (result.error or "")
    assert "LM Studio disconnected" in (result.error or "")
    assert q.health()["errored"] == 1

    # Worker is still healthy
    r1_2 = _make_mock_r1(verdict="PASS")
    q._r1 = r1_2  # swap client mid-life (allowed in tests)
    rid2 = await q.submit(_make_request())
    result2 = await q.get_result(rid2, timeout=2.0)
    assert result2.verdict == AuditVerdict.PASS

    await q.stop()


# ============================================
# 9. get_status() is non-blocking
# ============================================


@pytest.mark.asyncio
async def test_get_status_non_blocking():
    """get_status() returns immediately even when the audit is
    still in flight. It is purely a dict lookup."""
    r1 = _make_mock_r1(delay=0.50)
    q = AsyncAuditQueue(r1_client=r1, worker_count=1)
    await q.start()

    rid = await q.submit(_make_request())
    # Worker just picked it up — give it a tick
    await asyncio.sleep(0.05)

    t0 = time.monotonic()
    for _ in range(100):
        status = q.get_status(rid)
        assert status in (AuditVerdict.PENDING, AuditVerdict.IN_PROGRESS)
    elapsed = time.monotonic() - t0

    # 100 lookups should be effectively instant (< 0.05s)
    assert elapsed < 0.05, f"get_status() too slow: {elapsed:.3f}s for 100 calls"

    # Cleanup
    await q.get_result(rid, timeout=2.0)
    await q.stop()


# ============================================
# 10. stop() graceful shutdown
# ============================================


@pytest.mark.asyncio
async def test_stop_graceful_shutdown():
    """stop(drain=True) lets in-flight items finish, then exits.
    stop(drain=False) cancels workers immediately."""
    # Drain path
    r1 = _make_mock_r1(delay=0.10)
    q = AsyncAuditQueue(r1_client=r1, worker_count=2)
    await q.start()

    rid = await q.submit(_make_request())
    await q.get_result(rid, timeout=2.0)

    await q.stop(drain=True, timeout=2.0)
    assert q._running is False
    assert q._workers == []

    # Now the non-drain path: submit and stop immediately
    r1_slow = _make_mock_r1(delay=10.0)
    q2 = AsyncAuditQueue(r1_client=r1_slow, worker_count=1)
    await q2.start()
    await q2.submit(_make_request())
    await q2.stop(drain=False, timeout=2.0)
    assert q2._running is False
    assert q2._workers == []


# ============================================
# Bonus: singleton factory
# ============================================


@pytest.mark.asyncio
async def test_singleton_factory_returns_same_instance():
    """get_audit_queue() is a process-wide singleton. Second call
    returns the same instance even with different kwargs."""
    r1 = _make_mock_r1()
    q1 = get_audit_queue(r1_client=r1, worker_count=1)
    q2 = get_audit_queue(r1_client=r1)  # kwargs ignored
    assert q1 is q2

    # First call without r1_client on a fresh singleton raises
    reset_audit_queue()
    with pytest.raises(ValueError, match="r1_client is required"):
        get_audit_queue()


# ============================================
# Bonus: DROP_OLDEST evicts the head of the queue
# ============================================


@pytest.mark.asyncio
async def test_drop_oldest_evicts_head():
    """With DROP_OLDEST, submitting to a full queue evicts the
    oldest PENDING item (marking it ERROR) and makes room."""
    r1 = _make_mock_r1(delay=10.0)  # never finishes during the test
    q = AsyncAuditQueue(
        r1_client=r1,
        worker_count=1,
        max_queue_size=2,
        backpressure=BackpressurePolicy.DROP_OLDEST,
    )
    await q.start()

    rid_oldest = await q.submit(_make_request())
    await q.submit(_make_request())
    # Both queued; worker is busy on rid_oldest (slow mock), so the
    # 2nd item is sitting in the queue. Now submit a 3rd.
    rid_new = await q.submit(_make_request())
    assert rid_oldest != rid_new

    # The oldest pending item should be evicted.
    # The worker is mid-rid_oldest (we used the slow mock); the
    # queue held rid_2nd before, now it should be evicted and
    # rid_new placed.
    # We can check: there should be a result with verdict=ERROR
    # for some pending request_id. Find the evicted one.
    await asyncio.sleep(0.05)
    evicted = None
    for stored_rid, res in q._results.items():
        if res.verdict == AuditVerdict.ERROR and "dropped" in (res.error or ""):
            evicted = stored_rid
            break
    assert evicted is not None, "DROP_OLDEST did not evict any item"

    await q.stop(drain=False)
