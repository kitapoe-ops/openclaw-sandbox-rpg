"""
Unit tests for PhysicsLock v3.0 (F1-wide semantic state machine).

The PhysicsLock API moved into :mod:`backend.state_machine` as part
of the F1-wide refactor (2026-06-05). The legacy ``validate_choice``
/ ``validate_choices`` 2-tuple methods were replaced by:

  * ``PhysicsLock.validate(text, state_tags)`` → dict sync fast-path
  * ``PhysicsLock.is_action_allowed(...)`` → async R1-audited path

This file is updated to test the new API. The semantic intent of
each test is preserved; only the call shape changes.
"""
import pytest

from backend.physics_lock import PhysicsLock
from backend.state_machine import PhysicsLock as _PLCanonical  # source of truth


def _assert_is_the_same_class():
    """Sanity check: backend.physics_lock.PhysicsLock is the same class
    as backend.state_machine.PhysicsLock. If the re-export ever drifts,
    this will fail loudly."""
    assert PhysicsLock is _PLCanonical, (
        "PhysicsLock re-export in backend.physics_lock is out of sync with "
        "backend.state_machine.PhysicsLock — fix the re-export."
    )


class TestPhysicsLock:
    """Test physics lock validation (sync fast-path)."""

    def test_no_active_effects(self):
        _assert_is_the_same_class()
        lock = PhysicsLock()
        result = lock.validate("用劍斬向敵人", [])
        assert result["allowed"] is True
        assert result["reason"] == "ok"

    def test_forbidden_action_detected(self):
        _assert_is_the_same_class()
        lock = PhysicsLock()
        result = lock.validate("狂奔逃離現場", ["雙腿嚴重骨折"])
        assert result["allowed"] is False
        assert "雙腿嚴重骨折" in result["reason"]

    def test_multiple_active_effects(self):
        _assert_is_the_same_class()
        lock = PhysicsLock()
        # Either effect should block the action.
        result = lock.validate("觀察周圍環境", ["失明", "聾啞"])
        assert result["allowed"] is False

    def test_custom_rules(self):
        _assert_is_the_same_class()
        custom = {"custom_state": ["custom_forbidden_action"]}
        lock = PhysicsLock(custom_rules=custom)
        result = lock.validate("custom_forbidden_action here", ["custom_state"])
        assert result["allowed"] is False

    @pytest.mark.asyncio
    async def test_validate_choices_batch(self):
        """v3.0 PhysicsLock validates choices via the async R1 path.

        The legacy ``validate_choices`` batch method is replaced by
        per-action ``is_action_allowed`` calls (each with its own R1
        audit). The sync fast-path (``validate``) is used for
        in-process checks. This test exercises the sync fast-path on
        a batch, which is the closest semantic equivalent of the
        legacy batch validator.
        """
        _assert_is_the_same_class()
        lock = PhysicsLock()
        state_tags = ["左臂骨折"]
        choices = [
            {"id": "opt_01", "text": "用雙手握劍攻擊"},
            {"id": "opt_02", "text": "用單手握劍"},
            {"id": "opt_03", "text": "投擲匕首"},
        ]
        # Sync fast-path batch (no audit_queue wired → no R1 round-trip).
        for choice in choices:
            result = lock.validate(choice["text"], state_tags)
            choice["physics_lock_result"] = result
        # opt_01 and opt_03 should be flagged (forbidden actions for
        # left-arm fracture).
        assert choices[0]["physics_lock_result"]["allowed"] is False
        assert choices[1]["physics_lock_result"]["allowed"] is True
        assert choices[2]["physics_lock_result"]["allowed"] is False
