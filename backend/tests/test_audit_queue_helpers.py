"""
Tests for audit_queue.py singleton + helper functions.

audit_queue.py had 44 uncovered lines as of Phase H3 coverage
measurement. Of those, the singleton factory `get_audit_queue()`
and `reset_audit_queue()` together account for ~25 lines, and the
test was simple to write because the singleton is a pure-Python
module-level global — no async, no I/O, no real R1 client.

This file covers:
  * First call to get_audit_queue() with r1_client=None -> ValueError
  * First call constructs the queue and stores it as the singleton
  * Second call returns the same instance
  * Second call with a different r1_client logs a warning and still
    returns the original instance
  * reset_audit_queue() clears the singleton so the next call
    re-constructs it

We use AsyncMock for r1_client because the queue's __init__ may
call into it, and we want to avoid the R1 network call entirely.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import audit_queue
from backend.audit_queue import get_audit_queue, reset_audit_queue
from backend.audit_queue import AsyncAuditQueue


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the singleton before AND after each test so order
    independence is preserved across the suite."""
    audit_queue.audit_queue = None
    yield
    audit_queue.audit_queue = None


class TestGetAuditQueue:
    """get_audit_queue() is a module-level singleton factory.

    Reference: backend/audit_queue.py around line 590.
    """

    def test_first_call_with_none_raises_value_error(self) -> None:
        # r1_client is required on first construction
        with pytest.raises(ValueError, match="r1_client is required"):
            get_audit_queue(r1_client=None)

    def test_first_call_constructs_and_stores_singleton(self) -> None:
        mock_r1 = MagicMock(name="r1_client")
        queue = get_audit_queue(r1_client=mock_r1)
        assert isinstance(queue, AsyncAuditQueue)
        # The module-level singleton is now set
        assert audit_queue.audit_queue is queue
        # The stored r1_client is the one we passed in
        assert queue._r1 is mock_r1

    def test_second_call_returns_same_instance(self) -> None:
        mock_r1 = MagicMock(name="r1_client_first")
        queue1 = get_audit_queue(r1_client=mock_r1)
        # Second call without r1_client (None is OK after first init)
        queue2 = get_audit_queue(r1_client=None)
        assert queue1 is queue2

    def test_second_call_with_different_r1_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        first_r1 = MagicMock(name="r1_first")
        second_r1 = MagicMock(name="r1_second")

        # First call establishes singleton with first_r1
        get_audit_queue(r1_client=first_r1)

        # Second call with a DIFFERENT r1_client should warn but
        # still return the original singleton
        with caplog.at_level(logging.WARNING, logger="backend.audit_queue"):
            queue2 = get_audit_queue(r1_client=second_r1)

        # Singleton is unchanged — still the first one
        assert queue2._r1 is first_r1
        assert "different r1_client" in caplog.text

    def test_kwargs_after_first_call_are_ignored(self) -> None:
        # Skipped: get_audit_queue(**kwargs) forwards kwargs to
        # AsyncAuditQueue.__init__(), but AsyncAuditQueue currently
        # doesn't accept any kwargs (its signature is __init__(self,
        # r1_client)). If you call get_audit_queue(r1_client=x,
        # maxsize=10), it raises TypeError. The factory's **kwargs
        # parameter is a footgun — the test would be valuable once
        # AsyncAuditQueue either accepts kwargs or get_audit_queue
        # stops forwarding them. Tracked for Phase K.
        pytest.skip("AsyncAuditQueue.__init__ doesn't accept **kwargs")


class TestResetAuditQueue:
    """reset_audit_queue() clears the singleton so the next
    get_audit_queue() call re-constructs it."""

    def test_reset_clears_singleton(self) -> None:
        mock_r1 = MagicMock(name="r1_client")
        queue1 = get_audit_queue(r1_client=mock_r1)
        assert audit_queue.audit_queue is not None

        reset_audit_queue()
        assert audit_queue.audit_queue is None

    def test_after_reset_next_call_reconstructs(self) -> None:
        first_r1 = MagicMock(name="first")
        second_r1 = MagicMock(name="second")

        get_audit_queue(r1_client=first_r1)
        reset_audit_queue()
        # Next call must re-construct with a new r1_client
        queue2 = get_audit_queue(r1_client=second_r1)
        assert queue2._r1 is second_r1
        # And r1_client=None after reset raises (it's a fresh first-call)
        reset_audit_queue()
        with pytest.raises(ValueError, match="r1_client is required"):
            get_audit_queue(r1_client=None)

    def test_reset_when_no_singleton_is_noop(self) -> None:
        # If the singleton was never created, reset_audit_queue is a no-op
        assert audit_queue.audit_queue is None
        reset_audit_queue()  # should not raise
        assert audit_queue.audit_queue is None
