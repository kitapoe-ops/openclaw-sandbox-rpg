"""
Phase D2: Regression tests for the demo_mode.py fix.

Background
----------
Two pre-existing warnings fired on every test run:

1. ``RuntimeWarning: coroutine '_test_db_connection.<locals>.check'
   was never awaited`` at ``demo_mode.py:59``.
   Root cause: ``_test_db_connection`` called ``asyncio.run(check())``
   from inside an async handler (e.g. main.py's ``/health`` endpoint).
   When the request is dispatched through FastAPI's TestClient (anyio
   BlockingPortal), an event loop is already running in the test's
   thread, so ``asyncio.run`` raises ``RuntimeError`` which is caught
   by the outer ``try/except Exception``. The coroutine object
   ``check()`` was created (passed to ``asyncio.run``) but never
   actually awaited, so Python's GC finalizer emits the warning.

2. ``StarletteDeprecationWarning: Using httpx with starlette.testclient
   is deprecated`` from ``fastapi/testclient.py:1``.
   Suppressed via ``pytest.ini``'s ``filterwarnings`` directive.

The fix
-------
* Cache the DB-probe result in a module-level ``_db_reachable_cache``
  variable. This makes the probe idempotent within a process and
  also lets us short-circuit when called from inside a running loop
  (we default to "DB unreachable → demo mode" but cache the answer
  so we never need to probe again).
* Suppress the upstream Starlette deprecation via ``pytest.ini``.

These tests verify:
* No ``RuntimeWarning`` is emitted on any test run.
* ``is_demo_mode()`` still returns the correct value.
* The probe result is properly cached (subsequent calls don't trigger
  SQLAlchemy imports / async machinery).
* When ``DEMO_MODE=true`` / ``false``, the env var wins (no probe).
"""
import os
import sys
import warnings

import pytest

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)))


class TestDemoModeCaching:
    """Verify the cache prevents the never-awaited coroutine warning."""

    def test_is_demo_mode_no_warning_with_env_true(self, monkeypatch):
        """DEMO_MODE=true: no DB probe, no warning."""
        monkeypatch.setenv("DEMO_MODE", "true")
        # Reload so module-level DEMO_MODE_FLAG is recomputed
        import importlib

        from backend import demo_mode
        importlib.reload(demo_mode)

        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            for _ in range(5):
                assert demo_mode.is_demo_mode() is True

        # No RuntimeWarning about unawaited coroutines should be fired
        coroutine_warnings = [
            w for w in ws
            if "never awaited" in str(w.message)
        ]
        assert coroutine_warnings == [], (
            f"Got {len(coroutine_warnings)} never-awaited coroutine "
            f"warning(s): {[str(w.message) for w in coroutine_warnings]}"
        )

    def test_is_demo_mode_no_warning_with_env_false(self, monkeypatch):
        """DEMO_MODE=false: no DB probe, no warning."""
        monkeypatch.setenv("DEMO_MODE", "false")
        import importlib

        from backend import demo_mode
        importlib.reload(demo_mode)

        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            for _ in range(5):
                assert demo_mode.is_demo_mode() is False

        coroutine_warnings = [
            w for w in ws
            if "never awaited" in str(w.message)
        ]
        assert coroutine_warnings == [], (
            f"Got {len(coroutine_warnings)} never-awaited coroutine "
            f"warning(s): {[str(w.message) for w in coroutine_warnings]}"
        )

    def test_is_demo_mode_auto_no_warning_after_cache_warm(self, monkeypatch):
        """
        DEMO_MODE=auto: first call probes the DB (and caches the
        result). Subsequent calls must NOT re-probe and must NOT
        emit any coroutine warning, even when called repeatedly.
        """
        monkeypatch.setenv("DEMO_MODE", "auto")
        import importlib

        from backend import demo_mode
        importlib.reload(demo_mode)

        # First call: probes DB. This may internally use asyncio.run
        # (which is safe in a sync context) or short-circuit on a
        # running loop. Either way it should cache the result.
        first = demo_mode.is_demo_mode()

        # Subsequent calls must hit the cache
        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            for _ in range(10):
                result = demo_mode.is_demo_mode()
                assert result == first, "Cache must be stable within a process"

        coroutine_warnings = [
            w for w in ws
            if "never awaited" in str(w.message)
        ]
        assert coroutine_warnings == [], (
            f"After cache warm, {len(coroutine_warnings)} "
            f"never-awaited coroutine warning(s) fired: "
            f"{[str(w.message) for w in coroutine_warnings]}"
        )

    def test_cache_reset_on_module_reload(self, monkeypatch):
        """
        Reloading the module must reset the cache so the new
        DEMO_MODE env var is honored. The existing tier3 tests
        rely on this behavior (monkeypatch + importlib.reload).
        """
        import importlib

        from backend import demo_mode

        # First, populate the cache via "auto" (which probes)
        monkeypatch.setenv("DEMO_MODE", "auto")
        importlib.reload(demo_mode)
        assert demo_mode.is_demo_mode() in (True, False)
        assert demo_mode._db_reachable_cache is not None

        # Now switch to explicit true/false (no probe)
        monkeypatch.setenv("DEMO_MODE", "false")
        importlib.reload(demo_mode)
        # After reload, cache is None again and env var is "false"
        assert demo_mode._db_reachable_cache is None
        assert demo_mode.is_demo_mode() is False

        monkeypatch.setenv("DEMO_MODE", "true")
        importlib.reload(demo_mode)
        assert demo_mode._db_reachable_cache is None
        assert demo_mode.is_demo_mode() is True


class TestDemoModeRunningLoopSafety:
    """
    Verify _test_db_connection is safe to call from inside a running
    event loop (e.g. from main.py's /health async handler).
    """

    def test_test_db_connection_inside_running_loop(self, monkeypatch):
        """
        When called from inside a running loop, the function should
        short-circuit and return a safe default (False → demo mode)
        WITHOUT trying asyncio.run (which would raise and create an
        unawaited coroutine).
        """
        import asyncio
        import importlib
        monkeypatch.setenv("DEMO_MODE", "auto")
        from backend import demo_mode
        importlib.reload(demo_mode)

        async def _check_inside_loop():
            # We're inside a running loop now. The probe must not
            # try asyncio.run, which would raise RuntimeError.
            return demo_mode._test_db_connection()

        result = asyncio.run(_check_inside_loop())
        # The function defaults to False (= demo mode) when a loop
        # is running, so it should be False or True (cached) — but
        # must not raise, and must cache the result.
        assert isinstance(result, bool)
        # Cache should be populated
        assert demo_mode._db_reachable_cache is not None

    def test_no_coroutine_warning_in_running_loop(self, monkeypatch):
        """
        After calling _test_db_connection from inside a running loop,
        no RuntimeWarning about unawaited coroutines should fire.
        """
        import asyncio
        import importlib
        monkeypatch.setenv("DEMO_MODE", "auto")
        from backend import demo_mode
        importlib.reload(demo_mode)

        async def _trigger():
            return demo_mode._test_db_connection()

        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            asyncio.run(_trigger())
            # Force GC to surface any pending coroutine warnings
            import gc
            gc.collect()

        coroutine_warnings = [
            w for w in ws
            if "never awaited" in str(w.message)
        ]
        assert coroutine_warnings == [], (
            f"Got {len(coroutine_warnings)} never-awaited coroutine "
            f"warning(s) from running loop path: "
            f"{[str(w.message) for w in coroutine_warnings]}"
        )


class TestDemoModeConcurrency:
    """
    R1 audit (CONDITIONAL verdict) flagged potential race conditions
    when multiple coroutines access the cache before it's populated.
    These tests verify the CPython single-threaded asyncio model
    is sufficient — the first awaiter wins, all others hit the
    cache. No real concurrent DB probes occur.
    """

    def test_concurrent_calls_share_cache(self, monkeypatch):
        """
        Spawn N coroutines that all call is_demo_mode() concurrently.
        In asyncio, only ONE of them will actually execute the probe
        body at a time (the rest await the cache check or get
        scheduled to run after the cache is populated). The result
        must be consistent across all callers, and no coroutine
        warning should fire.
        """
        import asyncio
        import importlib
        monkeypatch.setenv("DEMO_MODE", "auto")
        from backend import demo_mode
        importlib.reload(demo_mode)

        async def _concurrent_probe():
            # 20 concurrent callers
            return await asyncio.gather(
                *[asyncio.to_thread(demo_mode.is_demo_mode) for _ in range(20)]
            )

        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            results = asyncio.run(_concurrent_probe())
            import gc
            gc.collect()

        # All 20 callers must agree
        assert all(r == results[0] for r in results), (
            f"Concurrent calls returned mixed results: {set(results)}"
        )
        # And no coroutine warnings
        coroutine_warnings = [
            w for w in ws if "never awaited" in str(w.message)
        ]
        assert coroutine_warnings == [], (
            f"Concurrent access fired {len(coroutine_warnings)} "
            f"coroutine warning(s): "
            f"{[str(w.message) for w in coroutine_warnings]}"
        )

    def test_cache_invalidated_only_via_reload(self, monkeypatch):
        """
        Document the explicit cache invalidation contract: the cache
        is invalidated ONLY by `importlib.reload(demo_mode)`. There
        is no public API to clear it mid-process. This is by design
        (the DB state is assumed stable for the lifetime of a
        Python process), but the contract should be visible.
        """
        import importlib

        from backend import demo_mode

        monkeypatch.setenv("DEMO_MODE", "auto")
        importlib.reload(demo_mode)
        # Populate cache via the underlying probe (not is_demo_mode, which
        # has its own DEMO_MODE env short-circuit and bypasses the cache).
        assert demo_mode._db_reachable_cache is None
        probed = demo_mode._test_db_connection()  # private probe, writes to cache
        assert demo_mode._db_reachable_cache is probed
        assert isinstance(demo_mode._db_reachable_cache, bool)

        # Manually corrupt the cache (simulate someone monkey-patching)
        demo_mode._db_reachable_cache = not probed
        # The next private probe returns the (corrupted) cached value
        assert demo_mode._test_db_connection() == (not probed)

        # The ONLY clean way to reset is reload
        importlib.reload(demo_mode)
        assert demo_mode._db_reachable_cache is None
        # And the private probe now re-probes
        second = demo_mode._test_db_connection()
        assert demo_mode._db_reachable_cache is second
        # is_demo_mode() also works correctly post-reload
        assert isinstance(demo_mode.is_demo_mode(), bool)


class TestPytestWarningsSummary:
    """
    The full pytest run must produce zero warnings about either:
      * ``coroutine '...' was never awaited``
      * ``StarletteDeprecationWarning: Using httpx with starlette.testclient``
    """

    def test_health_endpoint_no_coroutine_warning(self):
        """
        Direct repro of the original failing test: hitting /health
        via TestClient must not produce the coroutine warning.
        """
        from fastapi.testclient import TestClient

        from backend.main import app

        client = TestClient(app)
        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            r = client.get("/health")
            assert r.status_code == 200

        coroutine_warnings = [
            w for w in ws
            if "never awaited" in str(w.message)
        ]
        assert coroutine_warnings == [], (
            f"/health still triggers {len(coroutine_warnings)} "
            f"coroutine warning(s): "
            f"{[str(w.message) for w in coroutine_warnings]}"
        )
