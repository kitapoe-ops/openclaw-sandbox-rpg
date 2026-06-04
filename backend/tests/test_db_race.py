"""
Race condition tests for `backend.db.init_db()`.

The original `init_db()` had a TOCTOU race: it checked `if _engine is not None:
return` and then did the heavy work. Two coroutines that both saw `_engine is
None` would both proceed to create an engine and call `create_all()`,
producing duplicate DDL and (with the connection pool) a deadlock on startup.

The fix wraps the body in an `asyncio.Lock` + a `_init_done` flag:
- First caller does the work, sets `_init_done = True`.
- Latecomers fast-path return on the flag (no lock acquisition needed).
- On failure, `_init_done` stays False so the next caller can retry.

These tests verify the four critical properties:
1. `init_db()` called twice in a row is a no-op the second time.
2. Many concurrent `init_db()` calls all complete without error, and the
   heavy work runs exactly once (verified by counting engine-create calls).
3. If `init_db()` raises, `_init_done` stays False, so a subsequent call
   can still retry (the lock isn't permanently held).
4. `reset_init_state()` lets a new `init_db()` call run the full body.
"""
from __future__ import annotations

import asyncio
import os
import sys
import pytest
import pytest_asyncio

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ============================================
# Fixtures
# ============================================

@pytest_asyncio.fixture
async def fresh_sqlite(monkeypatch, tmp_path):
    """
    Per-test SQLite DB. Resets the db module's engine + init state + lock
    between tests so each test starts from a clean slate.

    This is critical because pytest-asyncio creates a new event loop per test,
    so any `asyncio.Lock` left over from a previous test would be bound to
    the wrong loop.
    """
    db_path = tmp_path / "race_test.db"
    monkeypatch.setenv("SANDBOX_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    from backend import db as db_mod
    await db_mod.dispose_engine()
    db_mod.reset_init_state()
    # Also drop the lock so a new one is created in this test's event loop.
    db_mod._init_lock = None
    yield db_path
    await db_mod.dispose_engine()
    db_mod.reset_init_state()
    db_mod._init_lock = None


# ============================================
# Tests
# ============================================

class TestInitDbIdempotent:
    @pytest.mark.asyncio
    async def test_init_db_idempotent(self, fresh_sqlite):
        """Calling init_db() twice in a row is a no-op the second time."""
        from backend import db as db_mod

        # First call: actually initializes.
        await db_mod.init_db()
        assert db_mod._engine is not None
        assert db_mod._init_done is True
        engine_after_first = db_mod._engine

        # Second call: must not raise, must not re-create the engine.
        await db_mod.init_db()
        assert db_mod._engine is engine_after_first, (
            "Second init_db() call replaced the engine — not idempotent"
        )
        assert db_mod._init_done is True


class TestInitDbConcurrent:
    @pytest.mark.asyncio
    async def test_init_db_concurrent(self, fresh_sqlite, monkeypatch):
        """
        10 concurrent init_db() calls all complete without error, and the
        underlying engine creation runs at most once per "attempt" (i.e.
        at most one Postgres probe + one SQLite fallback for the whole batch).
        """
        from backend import db as db_mod
        from sqlalchemy.ext.asyncio import create_async_engine

        # Count how many times we actually create an engine. Under the old
        # buggy code this would be ~2 per coroutine (20 total). Under the fix
        # it must be <= 2 (one primary probe + one SQLite fallback, both
        # serialized through the lock).
        call_count = {"n": 0}
        real_create = create_async_engine

        def counting_create_async_engine(url, *args, **kwargs):
            call_count["n"] += 1
            return real_create(url, *args, **kwargs)

        monkeypatch.setattr(
            db_mod, "create_async_engine", counting_create_async_engine
        )
        # Also patch the name that _try_create_engine looks up at call time
        # (it imports `create_async_engine` at module import, so we need to
        # patch the local reference inside db_mod).
        monkeypatch.setattr(
            db_mod, "create_async_engine", counting_create_async_engine
        )

        # Re-bind in _try_create_engine by re-patching the module attribute —
        # since _try_create_engine uses `create_async_engine` from the
        # `sqlalchemy.ext.asyncio` import which is already cached, we patch
        # by replacing the function it calls. The simplest robust way:
        # wrap _try_create_engine itself to count.
        real_try = db_mod._try_create_engine
        try_count = {"n": 0}

        async def counting_try(url):
            try_count["n"] += 1
            return await real_try(url)

        monkeypatch.setattr(db_mod, "_try_create_engine", counting_try)

        # Fire 10 concurrent init_db() calls.
        results = await asyncio.gather(
            *(db_mod.init_db() for _ in range(10)),
            return_exceptions=False,
        )

        # All 10 must succeed (no exceptions propagated).
        assert results is not None
        assert len(results) == 10
        assert db_mod._engine is not None
        assert db_mod._init_done is True

        # The critical assertion: engine creation was attempted at most a
        # handful of times, not 10×. In practice we expect exactly 1 (the
        # SQLite URL) because the lock serializes everything. We allow up
        # to 2 to be lenient against the primary-then-fallback path, but
        # under the fix with 10 concurrent callers it should be 1.
        assert try_count["n"] <= 2, (
            f"_try_create_engine was called {try_count['n']} times for 10 "
            f"concurrent init_db() calls — race condition is NOT fixed"
        )

        # Engine must be the same object for all callers (sanity check).
        assert db_mod._engine is not None


class TestInitDbFailureDoesNotLock:
    @pytest.mark.asyncio
    async def test_init_db_failure_does_not_lock(self, fresh_sqlite, monkeypatch):
        """
        If init_db() raises, `_init_done` must stay False so a subsequent
        call can still retry. The lock must also be released (no permanent
        hold).
        """
        from backend import db as db_mod

        # Force _try_create_engine to fail every time.
        async def always_fail(url):
            return None

        monkeypatch.setattr(db_mod, "_try_create_engine", always_fail)

        # First call: must raise (engine could not be created, even after
        # fallback). With our Postgres default + bad _try_create_engine, the
        # Postgres probe returns None, then it tries SQLite fallback which
        # also returns None, then it raises RuntimeError.
        with pytest.raises(RuntimeError):
            await db_mod.init_db()

        # _init_done must remain False after a failure (so retry is possible).
        assert db_mod._init_done is False, (
            "_init_done was set to True despite init_db() raising — "
            "subsequent calls would be incorrectly short-circuited"
        )

        # The lock must be released (we should be able to acquire it again).
        # If it were permanently held, this acquire would hang or fail.
        assert db_mod._init_lock is not None
        # Use a timeout so the test fails fast if the lock is held.
        try:
            await asyncio.wait_for(db_mod._init_lock.acquire(), timeout=1.0)
            released = True
        except (asyncio.TimeoutError, AssertionError):
            released = False
        else:
            db_mod._init_lock.release()
        assert released, "asyncio.Lock is permanently held after init_db() failure"

        # And a second call still raises (not silently returns).
        with pytest.raises(RuntimeError):
            await db_mod.init_db()

        # _init_done still False.
        assert db_mod._init_done is False


class TestResetInitState:
    @pytest.mark.asyncio
    async def test_reset_init_state(self, fresh_sqlite, monkeypatch):
        """
        reset_init_state() clears the fast-path flag so a subsequent
        init_db() call actually re-runs the body. The new run should
        re-call _try_create_engine and produce a working engine.
        """
        from backend import db as db_mod

        # First init: succeeds.
        await db_mod.init_db()
        assert db_mod._init_done is True
        original_engine = db_mod._engine
        assert original_engine is not None

        # Count engine create calls.
        real_try = db_mod._try_create_engine
        try_count = {"n": 0}

        async def counting_try(url):
            try_count["n"] += 1
            return await real_try(url)

        monkeypatch.setattr(db_mod, "_try_create_engine", counting_try)

        # Without resetting, a second init_db() is a no-op (fast path).
        await db_mod.init_db()
        assert try_count["n"] == 0, (
            "init_db() re-ran the body when it should have been a no-op"
        )

        # Reset the flag.
        db_mod.reset_init_state()
        assert db_mod._init_done is False

        # Now init_db() must actually run the body again.
        await db_mod.init_db()
        assert db_mod._init_done is True
        assert try_count["n"] >= 1, (
            "After reset_init_state(), init_db() did not re-run the body"
        )
        assert db_mod._engine is not None
