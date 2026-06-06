"""
Semantic State Machine tests (Phase F1-wide, 2026-06-05)
========================================================

Replaces the 19 legacy tests in `test_state_machine_tier1.py`
(deleted 2026-06-05). The 15 semantic invariants catalogued in
`docs/PHASE_F1_AUDIT.md` §2 are verified here, one test per
invariant, plus the 3 critical defenses (D1, D2, D3) and a handful
of constructor / edge-case tests.

Test design rules:
  * No `datetime` mocks — `updated_at` is checked via monotonicity,
    not exact values.
  * All Pydantic models use strict mode — invalid input is caught
    at construction time, not at apply time.
  * Physics Lock tests use a real `PhysicsLock` with a mock
    `audit_queue` (no R1 round-trip).
  * Memory Palace tests use a `MockMemoryPalace` that records
    every `remember()` call.

Run with:
    .venv/Scripts/python.exe -m pytest backend/tests/test_state_machine_semantic.py -q
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

# ============================================
# Fixtures
# ============================================


@pytest.fixture
def sm() -> SemanticStateMachine:
    """A fresh SemanticStateMachine with no audit/memory wiring."""
    from backend.state_machine import SemanticStateMachine

    return SemanticStateMachine()


@pytest.fixture
def sm_with_audit() -> SemanticStateMachine:
    """A SemanticStateMachine with a mock audit_queue for D1 tests."""
    from backend.state_machine import SemanticStateMachine

    audit_queue = MagicMock()
    return SemanticStateMachine(audit_queue=audit_queue)


class MockMemoryPalace:
    """In-memory recorder for `feed_memory_palace` tests (D3)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def remember(self, character_id: str, content: str, **kwargs: Any) -> str:
        self.calls.append(
            {
                "character_id": character_id,
                "content": content,
                **kwargs,
            }
        )
        return f"mem_{len(self.calls)}"


@pytest.fixture
def mock_palace() -> MockMemoryPalace:
    return MockMemoryPalace()


# ============================================
# Section A — 15 semantic invariants
# ============================================


# Invariant #1 — add a status tag
def test_invariant_1_add_status_tag(sm: SemanticStateMachine) -> None:
    """Status tags can be added to a character's active_effects."""
    from backend.state_machine import StateMutation

    m = StateMutation(character_id="c1", add_state=["右手骨折"], reason="戰鬥受傷")
    sm.apply_mutations([m])
    sm.apply_mutations([m])
    state = sm.get("c1")
    assert state is not None
    assert "右手骨折" in state.tags


# Invariant #2 — remove a status tag
def test_invariant_2_remove_status_tag(sm: SemanticStateMachine) -> None:
    """Status tags can be removed."""
    from backend.state_machine import StateMutation

    sm.apply_mutations(
        [StateMutation(character_id="c1", add_state=["右手骨折"], reason="受傷")]
    )
    sm.apply_mutations(
        [StateMutation(character_id="c1", remove_state=["右手骨折"], reason="治癒")]
    )
    state = sm.get("c1")
    assert "右手骨折" not in state.tags


# Invariant #3 — remove missing tag is silent no-op
def test_invariant_3_remove_missing_noop(sm: SemanticStateMachine) -> None:
    """Removing a non-existent tag is a silent no-op (LLM not penalized)."""
    from backend.state_machine import StateMutation

    report = sm.apply_mutations(
        [
            StateMutation(
                character_id="c1", remove_state=["從未添加"], reason="typo"
            )
        ]
    )
    # Mutation still applied (its sub-effects were zero).
    assert len(report["applied"]) == 1
    assert report["applied"][0]["tags"]["removed"] == []


# Invariant #4 — re-adding an existing tag is idempotent
def test_invariant_4_re_add_idempotent(sm: SemanticStateMachine) -> None:
    """Re-adding a tag does NOT create a duplicate."""
    from backend.state_machine import StateMutation

    sm.apply_mutations(
        [StateMutation(character_id="c1", add_state=["恐懼"], reason="目睹慘劇")]
    )
    sm.apply_mutations(
        [StateMutation(character_id="c1", add_state=["恐懼"], reason="再次目睹")]
    )
    state = sm.get("c1")
    assert state.tags.count("恐懼") == 1


# Invariant #5 — max 8 tags with deterministic eviction
def test_invariant_5_max_tags_eviction(sm: SemanticStateMachine) -> None:
    """Tag budget is bounded; lexicographic-last tag is evicted when full."""
    from backend.state_machine import StateMutation

    # Fill to 8 tags. Use CJK tags with varied strings.
    tags_to_add = [
        "狀態甲", "狀態乙", "狀態丙", "狀態丁",
        "狀態戊", "狀態己", "狀態庚", "狀態辛",
    ]
    for tag in tags_to_add:
        sm.apply_mutations(
            [
                StateMutation(
                    character_id="c1",
                    add_state=[tag],
                    reason="fill",
                )
            ]
        )
    state = sm.get("c1")
    assert len(state.tags) == 8

    # Add a 9th. The lexicographic last of 狀態甲..狀態辛 is 狀態辛.
    sm.apply_mutations(
        [StateMutation(character_id="c1", add_state=["重要狀態"], reason="priority")]
    )
    state = sm.get("c1")
    assert len(state.tags) == 8
    assert "重要狀態" in state.tags
    # 狀態辛 is lexicographically last → evicted
    assert "狀態辛" not in state.tags


# Invariant #6 — stamina scalar change
def test_invariant_6_stamina_change(sm: SemanticStateMachine) -> None:
    """Stamina is a pure-text string (no numbers)."""
    from backend.state_machine import StateMutation

    sm.apply_mutations(
        [
            StateMutation(
                character_id="c1",
                stamina="微喘",
                reason="長途行軍",
            )
        ]
    )
    state = sm.get("c1")
    assert state.stamina == "微喘"


# Invariant #7 — health scalar change
def test_invariant_7_health_change(sm: SemanticStateMachine) -> None:
    """Health is a pure-text string."""
    from backend.state_machine import StateMutation

    sm.apply_mutations(
        [
            StateMutation(
                character_id="c1",
                health="受傷",
                reason="戰鬥中箭",
            )
        ]
    )
    state = sm.get("c1")
    assert state.health == "受傷"


# Invariant #8 — morale scalar change
def test_invariant_8_morale_change(sm: SemanticStateMachine) -> None:
    """Morale is a pure-text string."""
    from backend.state_machine import StateMutation

    sm.apply_mutations(
        [
            StateMutation(
                character_id="c1",
                morale="焦慮",
                reason="目睹慘劇",
            )
        ]
    )
    state = sm.get("c1")
    assert state.morale == "焦慮"


# Invariant #9 — consume 1 of 3, leaves 2
def test_invariant_9_consume_partial(sm: SemanticStateMachine) -> None:
    """Item quantities are decremented; partially-consumed items persist."""
    from backend.state_machine import ItemConsumed, StateMutation

    sm.register(
        _state_with_inventory(
            "c1", items=[{"item_id": "藥水", "quantity": 3}]
        )
    )
    sm.apply_mutations(
        [
            StateMutation(
                character_id="c1",
                items_consumed=[ItemConsumed(item_id="藥水", quantity=1)],
                reason="治療",
            )
        ]
    )
    state = sm.get("c1")
    items = state.inventory["items"]
    potion = next(i for i in items if i["item_id"] == "藥水")
    assert potion["quantity"] == 2


# Invariant #10 — consume last item, removed
def test_invariant_10_consume_last_removed(sm: SemanticStateMachine) -> None:
    """Quantity 0 ⇒ item is removed from inventory."""
    from backend.state_machine import ItemConsumed, StateMutation

    sm.register(
        _state_with_inventory(
            "c1", items=[{"item_id": "藥水", "quantity": 1}]
        )
    )
    sm.apply_mutations(
        [
            StateMutation(
                character_id="c1",
                items_consumed=[ItemConsumed(item_id="藥水", quantity=1)],
                reason="治療",
            )
        ]
    )
    state = sm.get("c1")
    assert not any(i["item_id"] == "藥水" for i in state.inventory["items"])


# Invariant #11 — consume unknown item is silent no-op
def test_invariant_11_consume_unknown_noop(sm: SemanticStateMachine) -> None:
    """Unknown item IDs do not raise."""
    from backend.state_machine import ItemConsumed, StateMutation

    # No error raised. State is unchanged.
    sm.apply_mutations(
        [
            StateMutation(
                character_id="c1",
                items_consumed=[ItemConsumed(item_id="不存在", quantity=1)],
                reason="typo",
            )
        ]
    )
    state = sm.get("c1")
    assert state.inventory["items"] == []


# Invariant #12 — single memory appended
def test_invariant_12_single_memory(sm: SemanticStateMachine) -> None:
    """New memories are appended to the character's memory list."""
    from backend.state_machine import StateMutation

    sm.apply_mutations(
        [
            StateMutation(
                character_id="c1",
                new_memories=["第一次冒險"],
                reason="回憶",
            )
        ]
    )
    state = sm.get("c1")
    assert "第一次冒險" in state.memories


# Invariant #13 — multiple memories preserve order
def test_invariant_13_memories_order(sm: SemanticStateMachine) -> None:
    """Memory list preserves input order."""
    from backend.state_machine import StateMutation

    sm.apply_mutations(
        [
            StateMutation(
                character_id="c1",
                new_memories=["mem1", "mem2", "mem3"],
                reason="batch",
            )
        ]
    )
    state = sm.get("c1")
    assert state.memories == ["mem1", "mem2", "mem3"]


# Invariant #14 — relationship update
def test_invariant_14_relationship_update(sm: SemanticStateMachine) -> None:
    """NPC relationships are stored as dict[npc_id, str]."""
    from backend.state_machine import RelationshipChange, StateMutation

    sm.apply_mutations(
        [
            StateMutation(
                character_id="c1",
                relationship_changes=[
                    RelationshipChange(npc_id="npc_merchant", new_relationship="友好")
                ],
                reason="完成交易",
            )
        ]
    )
    state = sm.get("c1")
    assert state.relationships["npc_merchant"] == "友好"


# Invariant #15 — invalid relationship value silently accepted
def test_invariant_15_invalid_relationship_accepted(sm: SemanticStateMachine) -> None:
    """Per audit finding #15, preserve-as-bug: any string is accepted.

    The LLM-facing contract does not enforce an enum for relationship
    values. R1 catches garbage semantically. (F2 may add an enum.)
    """
    from backend.state_machine import RelationshipChange, StateMutation

    sm.apply_mutations(
        [
            StateMutation(
                character_id="c1",
                relationship_changes=[
                    RelationshipChange(npc_id="npc_x", new_relationship="香蕉")
                ],
                reason="LLM typo test",
            )
        ]
    )
    state = sm.get("c1")
    assert state.relationships["npc_x"] == "香蕉"


# ============================================
# Section B — Defense D1: Physics Lock
# ============================================


@pytest.mark.asyncio
async def test_physics_lock_allowed_when_no_forbidden_state() -> None:
    """A character with no forbidden state can perform any action (sync fast-path)."""
    from backend.state_machine import PhysicsLock

    lock = PhysicsLock()
    result = lock.validate("用劍斬向敵人", [])
    assert result == {"allowed": True, "reason": "ok"}


@pytest.mark.asyncio
async def test_physics_lock_rejects_forbidden_state() -> None:
    """A character with `雙腿嚴重骨折` cannot `狂奔`."""
    from backend.state_machine import PhysicsLock

    lock = PhysicsLock()
    result = lock.validate("狂奔逃離現場", ["雙腿嚴重骨折"])
    assert result["allowed"] is False
    assert "雙腿嚴重骨折" in result["reason"]


@pytest.mark.asyncio
async def test_physics_lock_async_passes_when_no_audit_queue() -> None:
    """Async is_action_allowed works without an audit queue (sync fast-path)."""
    from backend.state_machine import PhysicsLock

    lock = PhysicsLock(audit_queue=None)
    result = await lock.is_action_allowed(
        character_id="c1",
        action_text="用劍斬向敵人",
        state_tags=[],
    )
    assert result["allowed"] is True
    assert result["reason"] == "ok"


@pytest.mark.asyncio
async def test_physics_lock_timeout_fails_closed() -> None:
    """Defense D1: R1 audit timeout fails closed (action rejected).

    Mocks an audit_queue whose submit() never returns. The
    is_action_allowed call must:
      1. Reject the action (allowed=False).
      2. Return reason "R1_audit_timeout_fail_closed".
      3. NOT hang the main thread (must complete within ~5s + slack).
    """
    from backend.state_machine import PhysicsLock

    class HangingAuditQueue:
        async def submit(self, request: Any) -> str:
            await asyncio.sleep(60)  # never returns in time
            return "never"

        async def get_result(self, request_id: str, timeout: float | None = None) -> Any:
            await asyncio.sleep(60)
            return None

    lock = PhysicsLock(
        audit_queue=HangingAuditQueue(),
        timeout_s=0.2,  # accelerate the test (5s default would slow CI)
    )

    t0 = time.monotonic()
    result = await lock.is_action_allowed(
        character_id="c1",
        action_text="揮劍攻擊",
        state_tags=[],
    )
    elapsed = time.monotonic() - t0

    assert result["allowed"] is False
    assert result["reason"] == "R1_audit_timeout_fail_closed"
    # Must NOT hang: with timeout_s=0.2, total elapsed should be
    # well under 2 seconds (we add 1s slack for asyncio scheduling).
    assert elapsed < 2.0, f"is_action_allowed hung: {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_physics_lock_caches_repeated_calls() -> None:
    """Defense D1: second call with the same (state, action) hits the cache."""
    from backend.state_machine import PhysicsLock

    call_count = {"submit": 0}

    class CountingAuditQueue:
        async def submit(self, request: Any) -> str:
            call_count["submit"] += 1
            return f"req_{call_count['submit']}"

        async def get_result(self, request_id: str, timeout: float | None = None) -> Any:
            from backend.audit_queue import AuditResult, AuditVerdict

            return AuditResult(
                request_id=request_id,
                verdict=AuditVerdict.PASS,
            )

    lock = PhysicsLock(audit_queue=CountingAuditQueue(), timeout_s=2.0)
    # First call: R1 round-trip.
    r1 = await lock.is_action_allowed("c1", "揮劍", [])
    assert r1["allowed"] is True
    # Second call with identical (state, action) → cache hit, no R1.
    r2 = await lock.is_action_allowed("c1", "揮劍", [])
    assert r2["allowed"] is True
    assert call_count["submit"] == 1, "second call must hit the cache"
    assert lock._audit_cache_hits == 1


# ============================================
# Section C — Defense D2: JSON Schema Strict
# ============================================


def test_state_mutation_rejects_invalid_tag_chars() -> None:
    """Defense D2: emoji, Latin, and punctuation are rejected in tags."""
    from backend.state_machine import StateMutation

    with pytest.raises(ValidationError) as exc_info:
        StateMutation(character_id="c1", add_state=["💀骨折"], reason="x")
    assert "invalid characters" in str(exc_info.value).lower()

    with pytest.raises(ValidationError):
        StateMutation(character_id="c1", add_state=["broken arm"], reason="x")

    with pytest.raises(ValidationError):
        StateMutation(character_id="c1", add_state=["右手, 骨折!"], reason="x")


def test_state_mutation_rejects_too_long_tag() -> None:
    """Defense D2: tags longer than 15 chars are rejected."""
    from backend.state_machine import StateMutation

    with pytest.raises(ValidationError) as exc_info:
        StateMutation(
            character_id="c1",
            add_state=["右手腕粉碎性開放性骨折合併失血性休克"],  # >15 chars
            reason="x",
        )
    assert "too long" in str(exc_info.value).lower()


def test_state_mutation_rejects_extra_field() -> None:
    """Defense D2: extra="forbid" rejects unknown fields."""
    from backend.state_machine import StateMutation

    with pytest.raises(ValidationError) as exc_info:
        StateMutation(
            character_id="c1",
            add_state=["骨折"],
            reason="x",
            unknown_field="surprise",  # type: ignore[call-arg]
        )
    # Pydantic 2 raises "Extra inputs are not permitted"
    assert "extra" in str(exc_info.value).lower()


def test_state_mutation_atomicity() -> None:
    """Defense D2: one bad field = the WHOLE mutation is dropped.

    We can't construct a partial StateMutation (Pydantic rejects at
    construction), so we verify the contract at the apply_mutations
    layer: passing a non-StateMutation alongside a good one means
    the bad one is dropped but the good one still applies.
    """
    sm = _fresh_sm()
    from backend.state_machine import StateMutation

    good = StateMutation(character_id="c1", add_state=["骨折"], reason="x")
    bad = {"not": "a StateMutation"}  # type: ignore[dict-item]
    # apply_mutations should NOT raise; it should drop `bad` and
    # apply `good`.
    report = sm.apply_mutations([bad, good])  # type: ignore[list-item]
    assert len(report["applied"]) == 1
    assert len(report["dropped"]) == 1
    assert sm.get("c1").tags == ["骨折"]


def test_state_mutation_add_state_max_length_7() -> None:
    """Defense D2: a single mutation can add at most 7 tags."""
    from backend.state_machine import StateMutation

    with pytest.raises(ValidationError):
        StateMutation(
            character_id="c1",
            add_state=[f"狀態{i}" for i in range(8)],  # 8 > 7
            reason="x",
        )


# ============================================
# Section D — Defense D3: Memory Palace feed
# ============================================


def test_state_to_memory_string_bounds_length() -> None:
    """Defense D3: memory feed is bounded to 127 chars."""
    from backend.state_machine import SemanticState

    # 8 long tags (CJK only, no digits), joined → still capped.
    long_tags = [
        "很長的狀態標籤甲", "很長的狀態標籤乙", "很長的狀態標籤丙",
        "很長的狀態標籤丁", "很長的狀態標籤戊", "很長的狀態標籤己",
        "很長的狀態標籤庚", "很長的狀態標籤辛",
    ]
    state = SemanticState(character_id="c1", tags=long_tags)
    feed = state.to_memory_string()
    assert len(feed) <= 127
    # Verify the joined string starts with the first tag.
    assert "很長的狀態標籤甲" in feed
    # Empty state → "(no_state)"
    empty = SemanticState(character_id="c2")
    assert empty.to_memory_string() == "(no_state)"


def test_feed_memory_uses_tag_concatenation_not_narrative() -> None:
    """Defense D3: feed uses `;`-joined tags, NOT a free-form description."""
    from backend.state_machine import SemanticState, SemanticStateMachine

    sm = SemanticStateMachine(memory_palace=MockMemoryPalace())  # type: ignore[arg-type]
    sm.register(
        SemanticState(character_id="c1", tags=["右手骨折", "恐懼", "中毒"])
    )
    # Set up an async wrapper
    palace = sm._memory_palace  # type: ignore[attr-defined]
    sm._memory_palace = palace  # already correct

    asyncio.run(
        sm.feed_memory_palace(
            character_id="c1",
            narrative="一段很長的敘事文字講述了冒險的細節" * 10,
            current_state=sm.get("c1"),
        )
    )

    assert len(palace.calls) == 1
    content = palace.calls[0]["content"]
    # Tags are joined with `;`
    assert "右手骨折" in content
    assert "恐懼" in content
    assert "中毒" in content
    # The primary anchor is `state=...`
    assert content.startswith("state=")
    # Length is bounded to 127
    assert len(content) <= 127


def test_duplicate_tag_fuzzy_rejected() -> None:
    """Defense D3: overly-similar tags are rejected to prevent pollution."""
    from backend.state_machine import StateMutation

    sm = _fresh_sm()
    # '右手骨折' and '右手骨折x' share 4 of 5 unique chars → Jaccard 0.8.
    # '右手骨折' and '右手骨折啊' share 4 of 6 unique chars → Jaccard ~0.67.
    # We use tags that share most characters to push Jaccard > 0.85.
    sm.apply_mutations(
        [StateMutation(character_id="c1", add_state=["右手骨折"], reason="x")]
    )
    # Adding '右手骨折' again is idempotent (invariant #4).
    sm.apply_mutations(
        [StateMutation(character_id="c1", add_state=["右手骨折"], reason="x")]
    )
    state = sm.get("c1")
    assert state.tags == ["右手骨折"]
    # Now adding a near-duplicate that overlaps > 85% chars.
    # '右手骨折' = {右,手,骨,折}; we need a new tag with 4+ of those
    # characters in common. '骨折右手' = {骨,折,右,手} — same set!
    # Jaccard = 4/4 = 1.0 → must be rejected.
    sm.apply_mutations(
        [StateMutation(character_id="c1", add_state=["骨折右手"], reason="x")]
    )
    state = sm.get("c1")
    # The duplicate was rejected, so only the original is present.
    assert state.tags == ["右手骨折"]
    rejected = sm.apply_mutations(
        [StateMutation(character_id="c1", add_state=["骨折右手"], reason="x")]
    )["applied"][0]["tags"]
    assert "骨折右手" in rejected.get("rejected_duplicates", [])


# ============================================
# Section E — Misc / constructor / edge cases
# ============================================


def test_semantic_state_constructor_validates_tags() -> None:
    """SemanticState constructor enforces the same rules as Defense D2."""
    from backend.state_machine import SemanticState, StateValidationError

    with pytest.raises(StateValidationError):
        SemanticState(character_id="c1", tags=["💀"])
    with pytest.raises(StateValidationError):
        SemanticState(character_id="c1", tags=["x" * 16])
    with pytest.raises(StateValidationError):
        SemanticState(character_id="", tags=[])


def test_register_and_get_state() -> None:
    """The state store supports register/get/get_or_create."""
    from backend.state_machine import SemanticState, SemanticStateMachine

    sm = SemanticStateMachine()
    state = SemanticState(character_id="c1", tags=["骨折"])
    sm.register(state)
    assert sm.get("c1") is state
    # get_or_create for an unknown id
    created = sm.get_or_create("c_new")
    assert created.character_id == "c_new"
    assert created.tags == []


def test_apply_mutations_empty_list(sm: SemanticStateMachine) -> None:
    """An empty mutation list is a valid no-op."""
    report = sm.apply_mutations([])
    assert report == {"applied": [], "dropped": [], "side_effects_total": 0}


def test_apply_mutations_rejects_non_list(sm: SemanticStateMachine) -> None:
    """apply_mutations validates input is a list (audit finding #7)."""
    from backend.state_machine import StateMachineError

    with pytest.raises(StateMachineError):
        sm.apply_mutations("not a list")  # type: ignore[arg-type]
    with pytest.raises(StateMachineError):
        sm.apply_mutations({"not": "a list either"})  # type: ignore[arg-type]


def test_updated_at_advances_on_apply() -> None:
    """Every apply_mutations call advances updated_at (audit finding #8)."""
    from backend.state_machine import SemanticState, SemanticStateMachine, StateMutation

    sm = SemanticStateMachine()
    sm.register(SemanticState(character_id="c1"))
    t0 = sm.get("c1").updated_at()
    time.sleep(0.005)  # ensure clock advances
    sm.apply_mutations(
        [StateMutation(character_id="c1", stamina="微喘", reason="x")]
    )
    t1 = sm.get("c1").updated_at()
    assert t1 > t0


def test_action_to_text_extraction() -> None:
    """Defense D1 helper: extract gated text from action dicts."""
    from backend.state_machine import SemanticStateMachine

    # Explicit text
    assert (
        SemanticStateMachine._action_to_text({"text": "揮劍斬敵"}) == "揮劍斬敵"
    )
    # Verb + target
    assert (
        SemanticStateMachine._action_to_text({"verb": "揮劍", "target": "敵人"})
        == "揮劍 敵人"
    )
    # Verb only
    assert SemanticStateMachine._action_to_text({"verb": "休息"}) == "休息"
    # Empty
    assert SemanticStateMachine._action_to_text({}) == ""


# ============================================
# Helpers
# ============================================


def _fresh_sm():
    from backend.state_machine import SemanticStateMachine

    return SemanticStateMachine()


def _state_with_inventory(character_id: str, items: list):
    from backend.state_machine import SemanticState

    return SemanticState(
        character_id=character_id,
        inventory={"items": list(items)},
    )
