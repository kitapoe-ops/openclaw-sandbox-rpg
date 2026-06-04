"""
Tier 2 Race-Condition Tests for backend/db.py::init_db()
=========================================================

Phase B added `asyncio.Lock` + `_init_done` flag to prevent race conditions
on multi-worker / multi-coroutine startup. These tests protect that fix
so a future refactor cannot silently regress it.

Strategy
--------
- The default `engine` in backend/db.py points at a real Postgres
  (`postgresql+asyncpg://...`) which is NOT available in CI / unit tests.
- We replace the engine with a SQLite in-memory engine (aiosqlite) and
  patch `Base.metadata.create_all` with a spy / fake.
- The actual init_db() logic (`_init_done` flag, `asyncio.Lock`, the
  call to `Base.metadata.create_all`) is what we exercise; we don't need
  real Postgres semantics.
- We rely on `reset_init_state()` to clean up global state between tests.

These tests are STANDALONE — each test calls `reset_init_state()` in
setup_method so order does not matter.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import patch, MagicMock

import pytest

# Ensure repo root is on sys.path (mirrors test_api_tier3.py convention)
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from sqlalchemy.ext.asyncio import create_async_engine

import backend.db as db


# ============================================
# Fixtures
# ============================================
@pytest.fixture
def sqlite_engine():
    """Yield a fresh in-memory SQLite engine for the test, then dispose."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        yield engine
    finally:
        # Synchronous dispose — we tear down at fixture teardown.
        # (AsyncEngine.dispose is sync-friendly for the public API.)
        engine.sync_engine.dispose()


@pytest.fixture
def patched_init_env(sqlite_engine, monkeypatch):
    """
    Patch backend.db so init_db() works without a real Postgres:
      - `engine`  -> sqlite in-memory
      - `Base.metadata.create_all` -> MagicMock spy
    Also reset `_init_done` and `_init_lock` between tests.
    """
    # Reset global init state
    db.reset_init_state()
    # Force a fresh lock (it gets created on first init_db call anyway)
    monkeypatch.setattr(db, "_init_lock", None)
    # Replace the engine
    monkeypatch.setattr(db, "engine", sqlite_engine)
    # Spy on create_all
    spy = MagicMock()
    monkeypatch.setattr(db.Base.metadata, "create_all", spy)
    yield {"engine": sqlite_engine, "create_all_spy": spy}
    # Cleanup
    db.reset_init_state()


# ============================================
# Test class
# ============================================
@pytest.mark.asyncio
class TestInitDbRaceSafety:
    """Verify init_db() is safe to call concurrently / repeatedly."""

    async def test_init_db_idempotent_sync(self, patched_init_env):
        """
        Calling init_db() twice in a row must not raise, and the second
        call must be a no-op (create_all NOT invoked a second time).
        """
        spy = patched_init_env["create_all_spy"]

        # First call: should invoke create_all
        await db.init_db()
        assert spy.call_count == 1, (
            f"First init_db() should invoke create_all once, got {spy.call_count}"
        )

        # Second call: should early-return via _init_done flag
        await db.init_db()
        assert spy.call_count == 1, (
            f"Second init_db() should be no-op, create_all was called "
            f"{spy.call_count} times total"
        )

        # Third call for good measure
        await db.init_db()
        assert spy.call_count == 1, (
            f"Third init_db() should be no-op, create_all was called "
            f"{spy.call_count} times total"
        )

    async def test_init_db_concurrent_async(self, patched_init_env):
        """
        10 concurrent asyncio.gather(init_db()) calls must all complete
        without error. Verifies the asyncio.Lock + _init_done combo
        actually protects the critical section.
        """
        spy = patched_init_env["create_all_spy"]

        # 10 concurrent calls
        results = await asyncio.gather(
            *(db.init_db() for _ in range(10)),
            return_exceptions=True,
        )

        # None should have raised
        errors = [r for r in results if isinstance(r, BaseException)]
        assert not errors, (
            f"Concurrent init_db() raised {len(errors)} errors: "
            f"{[repr(e) for e in errors]}"
        )

    async def test_init_db_actually_initializes_once(self, patched_init_env):
        """
        Even with 10 concurrent calls, Base.metadata.create_all must be
        invoked EXACTLY once. This is the core race-safety property the
        Phase B fix was supposed to add.
        """
        spy = patched_init_env["create_all_spy"]

        await asyncio.gather(*(db.init_db() for _ in range(10)))

        assert spy.call_count == 1, (
            f"create_all should be called exactly once under concurrent "
            f"init_db(), got {spy.call_count} calls"
        )

    async def test_reset_init_state(self, patched_init_env):
        """
        After reset_init_state(), the next init_db() must re-run the
        create_all step (i.e. NOT short-circuit on _init_done).
        """
        spy = patched_init_env["create_all_spy"]

        # First init
        await db.init_db()
        assert spy.call_count == 1

        # Idempotent — no extra call
        await db.init_db()
        assert spy.call_count == 1

        # Reset — next call should re-invoke create_all
        db.reset_init_state()
        await db.init_db()
        assert spy.call_count == 2, (
            f"After reset_init_state(), init_db() should re-invoke "
            f"create_all. Expected 2 total calls, got {spy.call_count}"
        )

        # Idempotent again
        await db.init_db()
        assert spy.call_count == 2, (
            f"Post-reset init_db() should also be idempotent. "
            f"Expected 2 total calls, got {spy.call_count}"
        )

    async def test_init_db_under_lock_does_not_deadlock(
        self, patched_init_env, monkeypatch
    ):
        """
        The asyncio.Lock should SERIALIZE concurrent calls — not
        DEADLOCK them. We give create_all a small artificial delay and
        then verify:
          (a) 10 concurrent calls all complete
          (b) total time is bounded (not 10x the single-call time)
          (c) create_all is still called exactly once

        Bounded by 5x the single-call work time — generous to absorb
        asyncio scheduling overhead on slow CI runners.
        """

        # Patch create_all with a slow async function (via sync wrapper)
        call_count = {"n": 0}

        def slow_create_all(*args, **kwargs):
            call_count["n"] += 1
            # Simulate a real DDL roundtrip
            time.sleep(0.05)  # 50ms
            return None

        monkeypatch.setattr(db.Base.metadata, "create_all", slow_create_all)

        # Baseline: single call timing
        t0 = time.perf_counter()
        await db.init_db()
        single_call_time = time.perf_counter() - t0

        # Reset for the concurrent test
        db.reset_init_state()
        call_count["n"] = 0

        # 10 concurrent calls
        t0 = time.perf_counter()
        await asyncio.gather(*(db.init_db() for _ in range(10)))
        concurrent_time = time.perf_counter() - t0

        # Assertions
        assert call_count["n"] == 1, (
            f"create_all should still be called exactly once under load, "
            f"got {call_count['n']}"
        )

        # Concurrent should NOT be 10x slower (that would mean no
        # serialization — every call ran the full body).
        # Allow up to 5x to absorb event-loop overhead on slow CI.
        upper_bound = single_call_time * 5 + 0.5  # +0.5s slack
        assert concurrent_time < upper_bound, (
            f"10 concurrent init_db() took {concurrent_time:.3f}s; "
            f"single call took {single_call_time:.3f}s; "
            f"upper bound = {upper_bound:.3f}s. "
            f"Lock may be serializing badly or deadlocking."
        )

        # And concurrent should NOT be much LESS than single (sanity check
        # that the lock actually waited for the first to finish).
        # Use a softer lower bound: concurrent >= single_call_time * 0.5
        # (event-loop can finish concurrent in less than 1x if first call
        # does the work and others early-return on _init_done before
        # even acquiring the lock in the wait queue — but our impl
        # acquires first, then checks, so they queue briefly).
        # We just ensure it didn't take ZERO time (which would mean
        # create_all was never invoked).
        assert concurrent_time >= single_call_time * 0.5, (
            f"Concurrent time {concurrent_time:.3f}s is suspiciously fast "
            f"vs single {single_call_time:.3f}s. create_all may not have run."
        )
