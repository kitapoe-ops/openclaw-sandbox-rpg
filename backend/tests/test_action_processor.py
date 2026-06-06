"""
Phase E1 + F3 — Real HTTP /api/action/process processor tests
================================================================

Covers the ``backend.api.action_processor.ActionProcessor`` and its
``POST /api/action/process`` route on the composed app
(``backend.app_with_memory.app``). Mirrors the test patterns from
:mod:`backend.tests.test_d4_frontend_e2e` (ASGITransport + real
composed app) and :mod:`backend.tests.test_llm_client`
(MockLLMClient, no network).

Phase F3 updated this file: the legacy 8 tests were rewritten to
match the new flow (PromptBuilder + state-machine contract). 4
new tests were added for the F3 contract:

  F3-1. test_process_calls_prompt_builder_before_llm
  F3-2. test_process_persists_valid_mutation
  F3-3. test_process_drops_invalid_mutation
  F3-4. test_process_feeds_memory_palace_with_state_anchor

All tests are hermetic — no Postgres, no vector store, no real LLM.
The processor's ``memory_palace`` and ``turn_system`` are injected;
the LLM is always a ``MockLLMClient`` or an ``AsyncMock`` derivative.

Test inventory (12/12):
    1.  test_process_simple_action_returns_narrative
    2.  test_process_persists_to_memory_palace
    3.  test_process_invalid_verb_returns_400
    4.  test_process_missing_character_id_returns_422
    5.  test_process_uses_mock_llm_client
    6.  test_process_handles_llm_failure_gracefully
    7.  test_process_concurrent_actions_serialized
    8.  test_process_response_includes_action_id_uuid
    F3-1. test_process_calls_prompt_builder_before_llm
    F3-2. test_process_persists_valid_mutation
    F3-3. test_process_drops_invalid_mutation
    F3-4. test_process_feeds_memory_palace_with_state_anchor
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

# Ensure repo root on sys.path (same idiom as other backend tests).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.api.action_processor import (  # noqa: E402
    ALLOWED_VERBS,
    ActionProcessor,
    InMemoryTurnSystem,
    LLMUnavailableError,
    ProcessActionRequest,
    ProcessActionResponse,
    build_default_processor,
)
from backend.llm_client import MockLLMClient  # noqa: E402

# ============================================
# Fixtures
# ============================================


@pytest.fixture
def canned_narrative() -> str:
    """Phase F3: canned response is a JSON object matching the
    ``{"narrative": str, "state_mutations": {...} | null}`` shape.
    Tests that exercise the narrative path get ``narrative`` and
    ``mutation=None`` (no state change)."""
    return '{"narrative": "你環顧四周，鎮上空無一人，遠處傳來狼嚎。", ' '"state_mutations": null}'


@pytest.fixture
def mock_llm(canned_narrative: str) -> MockLLMClient:
    """Hermetic LLM mock — returns a canned narrative, counts calls."""
    return MockLLMClient(canned_response=canned_narrative)


@pytest.fixture
def mock_palace() -> AsyncMock:
    """A mock MemoryPalaceIntegration.

    The real ``remember()`` requires a length-EMBEDDING_DIM vector,
    a real Postgres session, and a vector store. We bypass all of
    that by mocking — the processor only cares that
    ``remember(character_id, content, embedding, ...)`` returns a
    memory_id string.
    """
    palace = AsyncMock()
    palace.remember = AsyncMock(side_effect=lambda **kwargs: f"mem_{uuid.uuid4().hex[:8]}")
    return palace


@pytest.fixture
def fresh_processor(mock_llm: MockLLMClient, mock_palace: AsyncMock) -> ActionProcessor:
    """A fresh processor with mock LLM and mock palace, no shared state."""
    return ActionProcessor(
        llm_client=mock_llm,
        memory_palace=mock_palace,
        turn_system=InMemoryTurnSystem(),
    )


@pytest_asyncio.fixture
async def e1_client(mock_llm: MockLLMClient, mock_palace: AsyncMock) -> AsyncIterator[AsyncClient]:
    """Yield an AsyncClient bound to the *composed* app.

    We monkey-patch the module-level ``_e1_processor`` so the
    /api/action/process route uses our mock LLM + mock palace, not
    the production get_llm_client() factory.
    """
    from backend import app_with_memory as awm

    test_processor = ActionProcessor(
        llm_client=mock_llm,
        memory_palace=mock_palace,
        turn_system=InMemoryTurnSystem(),
    )
    prev = awm._e1_processor
    awm._e1_processor = test_processor
    try:
        transport = ASGITransport(app=awm.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        awm._e1_processor = prev


# ============================================
# 1. Simple action returns a narrative
# ============================================


@pytest.mark.asyncio
async def test_process_simple_action_returns_narrative(
    fresh_processor: ActionProcessor,
    canned_narrative: str,
) -> None:
    """POST a valid payload, get back a non-empty narrative string.

    Phase F3: the canned response is a JSON object with
    ``narrative`` and ``state_mutations`` fields. The processor
    extracts ``narrative`` from the parsed JSON. The ``state_mutations``
    is null (no state change) so ``mutation`` in the response is
    ``None`` and ``mutation_error`` is ``None``.
    """
    import json as _json

    parsed = _json.loads(canned_narrative)
    expected_narrative = parsed["narrative"]

    result = await fresh_processor.process(
        character_id="char_demo_player",
        verb="look",
        target="around",
    )

    assert result["status"] == "processed"
    assert isinstance(result["narrative"], str)
    assert result["narrative"], "narrative must be non-empty"
    # The mock LLM returns the canned JSON; the processor extracts
    # the ``narrative`` field.
    assert result["narrative"] == expected_narrative
    assert result["received"]["character_id"] == "char_demo_player"
    assert result["received"]["verb"] == "look"
    assert result["received"]["target"] == "around"
    # Phase F3: state_mutations is null in the canned response, so
    # the response carries ``mutation=None`` and no error.
    assert result["mutation"] is None
    assert result["mutation_error"] is None


# ============================================
# 2. Persists to Memory Palace
# ============================================


@pytest.mark.asyncio
async def test_process_persists_to_memory_palace(
    fresh_processor: ActionProcessor,
    mock_palace: AsyncMock,
) -> None:
    """After a successful process(), the mock palace's remember() was called."""
    await fresh_processor.process(
        character_id="char_demo_player",
        verb="search",
        target="the chest",
    )

    mock_palace.remember.assert_awaited_once()
    kwargs = mock_palace.remember.await_args.kwargs
    assert kwargs["character_id"] == "char_demo_player"
    assert "search" in kwargs["content"]
    assert "the chest" in kwargs["content"]
    assert kwargs["memory_type"] == "episodic"
    assert 0.0 <= kwargs["salience"] <= 1.0
    assert isinstance(kwargs["embedding"], list)
    assert len(kwargs["embedding"]) > 0  # non-zero
    # Metadata echoes the action_id we returned.
    assert "action_id" in kwargs["metadata"]


# ============================================
# 3. Invalid verb returns HTTPException 400
# ============================================


@pytest.mark.asyncio
async def test_process_invalid_verb_returns_400(
    fresh_processor: ActionProcessor,
) -> None:
    """An unknown verb raises HTTPException(400) with a useful detail."""
    with pytest.raises(HTTPException) as exc_info:
        await fresh_processor.process(
            character_id="char_demo_player",
            verb="yeet",  # not in the whitelist
            target="the dragon",
        )
    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert "Invalid verb" in detail or "yeet" in detail

    # Sanity: ALLOWED_VERBS does not contain "yeet".
    assert "yeet" not in ALLOWED_VERBS


# ============================================
# 4. Missing character_id returns 422 (Pydantic)
# ============================================


@pytest.mark.asyncio
async def test_process_missing_character_id_returns_422(
    e1_client: AsyncClient,
) -> None:
    """POST without character_id is rejected by Pydantic with 422."""
    # The Pydantic model enforces character_id presence on the
    # *route*, not on the underlying process() method. We test the
    # route here.
    resp = await e1_client.post(
        "/api/action/process",
        json={"verb": "look"},  # no character_id
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    # Pydantic surfaces the missing field.
    assert "detail" in body
    assert any(
        "character_id" in str(err.get("loc", [])) for err in body["detail"]
    ), f"expected character_id error, got {body['detail']!r}"


# ============================================
# 5. Uses MockLLMClient (no real network)
# ============================================


@pytest.mark.asyncio
async def test_process_uses_mock_llm_client(
    fresh_processor: ActionProcessor,
    mock_llm: MockLLMClient,
) -> None:
    """The processor delegates generation to the injected LLM client.

    The mock's ``calls`` counter is bumped exactly once. This test
    fails loudly if anyone swaps the LLM client to a real network
    one (MockLLMClient is hermetic by construction).
    """
    assert mock_llm.calls == 0

    await fresh_processor.process(
        character_id="char_demo_player",
        verb="inventory",
    )
    assert mock_llm.calls == 1

    # Second call also goes through the mock.
    await fresh_processor.process(
        character_id="char_demo_player",
        verb="wait",
    )
    assert mock_llm.calls == 2

    # Sanity: the response narrative came from the canned string.
    # (already covered by test 1; double-check here.)


# ============================================
# 6. Handles LLM failure gracefully (HTTP 500)
# ============================================


@pytest.mark.asyncio
async def test_process_handles_llm_failure_gracefully(
    fresh_processor: ActionProcessor,
) -> None:
    """If the LLM raises, the processor wraps it in LLMUnavailableError.

    The FastAPI dependency in the route would translate that to a
    500 response. We test the processor's contract directly.

    Phase F3: the processor calls ``generate_with_state_contract``,
    so we mock that method (not the legacy ``generate``). The
    behavior under failure is identical: a hard exception in the
    LLM call surfaces as ``LLMUnavailableError`` → 500.
    """
    failing_llm = AsyncMock()
    failing_llm.generate = AsyncMock(side_effect=RuntimeError("MiniMax-M3 timed out (simulated)"))
    failing_llm.generate_with_state_contract = AsyncMock(
        side_effect=RuntimeError("MiniMax-M3 timed out (simulated)")
    )
    processor = ActionProcessor(
        llm_client=failing_llm,
        memory_palace=None,
        turn_system=InMemoryTurnSystem(),
    )

    with pytest.raises(LLMUnavailableError) as exc_info:
        await processor.process(
            character_id="char_demo_player",
            verb="cast",
            target="fireball",
        )
    # The cause is the original exception.
    assert "timed out" in str(exc_info.value.__cause__)

    # And the FastAPI route surfaces it as 500.
    from backend import app_with_memory as awm

    prev = awm._e1_processor
    awm._e1_processor = processor
    try:
        transport = ASGITransport(app=awm.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/action/process",
                json={
                    "character_id": "char_demo_player",
                    "verb": "cast",
                    "target": "fireball",
                },
            )
        assert resp.status_code == 500, resp.text
        body = resp.json()
        assert "detail" in body
        assert "LLM unavailable" in body["detail"]
    finally:
        awm._e1_processor = prev


# ============================================
# 7. Concurrent actions are serialized
# ============================================


@pytest.mark.asyncio
async def test_process_concurrent_actions_serialized() -> None:
    """Two concurrent process() calls for the same character serialize.

    The second call must wait for the first to release the per-
    character physics lock. We prove this by having the LLM mock
    sleep 100ms, firing two coroutines, and checking that they
    complete sequentially (gap >= ~100ms between the two LLM calls)
    and the second call's response succeeds.

    Phase F3: the LLM is called via
    ``generate_with_state_contract``, so we override THAT method
    (not the legacy ``generate``) to record the timing. The
    canned response is a valid F3 JSON object.
    """

    # Slow LLM that records start time of each state-contract call.
    call_starts: list[float] = []

    slow_canned = '{"narrative": "Slow narrative.", "state_mutations": null}'

    class _SlowMock(MockLLMClient):
        async def generate_with_state_contract(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            call_starts.append(time.monotonic())
            await asyncio.sleep(0.1)  # 100ms — enough to overlap
            return await super().generate_with_state_contract(*args, **kwargs)

    slow_llm = _SlowMock(canned_response=slow_canned)
    processor = ActionProcessor(
        llm_client=slow_llm,
        memory_palace=None,
        turn_system=InMemoryTurnSystem(),
    )

    t0 = time.monotonic()
    results = await asyncio.gather(
        processor.process("char_demo_player", "look"),
        processor.process("char_demo_player", "wait"),
    )
    elapsed = time.monotonic() - t0

    # Both succeeded.
    assert len(results) == 2
    assert all(r["status"] == "processed" for r in results)

    # Two LLM calls were made.
    assert len(call_starts) == 2, f"expected 2 LLM calls, got {call_starts!r}"

    # The LLM calls were serialized — the second one started AFTER
    # the first one's 100ms sleep. We allow a tiny tolerance for
    # event-loop jitter.
    gap = call_starts[1] - call_starts[0]
    assert gap >= 0.08, (
        f"second LLM call started only {gap*1000:.1f}ms after the "
        f"first — concurrency was not serialized"
    )

    # Total elapsed is at least 200ms (two serial 100ms calls).
    assert elapsed >= 0.18, f"two serial 100ms calls took {elapsed*1000:.1f}ms"

    # The two action_ids are distinct (each call produced a new one).
    ids = {r["action_id"] for r in results}
    assert len(ids) == 2


# ============================================
# 8. action_id is a valid UUID4
# ============================================


@pytest.mark.asyncio
async def test_process_response_includes_action_id_uuid(
    e1_client: AsyncClient,
) -> None:
    """The response's action_id is a parseable UUID4 string."""
    resp = await e1_client.post(
        "/api/action/process",
        json={
            "character_id": "char_demo_player",
            "verb": "look",
            "target": "the horizon",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "processed"

    action_id = body["action_id"]
    assert isinstance(action_id, str)
    parsed = uuid.UUID(action_id)  # raises if not a valid UUID
    assert parsed.version == 4, f"expected UUID4, got version {parsed.version}"


# ============================================
# Bonus: Pydantic model round-trip
# ============================================


def test_process_action_request_validation() -> None:
    """ProcessActionRequest rejects bad payloads at the schema level."""
    # Empty verb is rejected.
    with pytest.raises(ValueError):
        ProcessActionRequest(character_id="c1", verb="")

    # Verb too long is rejected.
    with pytest.raises(ValueError):
        ProcessActionRequest(character_id="c1", verb="a" * 51)

    # Empty character_id is rejected.
    with pytest.raises(ValueError):
        ProcessActionRequest(character_id="", verb="look")

    # Minimal valid payload round-trips.
    req = ProcessActionRequest(character_id="c1", verb="look")
    assert req.target is None
    assert req.args is None

    # With target + args.
    req2 = ProcessActionRequest(
        character_id="c1",
        verb="attack",
        target="goblin",
        args={"weapon": "sword"},
    )
    assert req2.target == "goblin"
    assert req2.args == {"weapon": "sword"}


def test_process_action_response_default_side_effects() -> None:
    """Response has stable defaults — side_effects defaults to []."""
    resp = ProcessActionResponse(
        action_id=str(uuid.uuid4()),
        narrative="You wait.",
    )
    assert resp.status == "processed"
    assert resp.side_effects == []
    assert resp.received == {}


# ============================================
# Bonus: build_default_processor factory smoke test
# ============================================


def test_build_default_processor_uses_mock_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no env set, the factory builds a MockLLMClient-backed processor."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    proc = build_default_processor()
    assert isinstance(proc, ActionProcessor)
    assert isinstance(proc.turn_system, InMemoryTurnSystem)
    # The default LLM client is MockLLMClient (no api key set).
    from backend.llm_client import MockLLMClient as _MLC

    assert isinstance(proc.llm_client, _MLC)


# ============================================
# Phase F3: 4 new tests for the wiring contract
# ============================================


@pytest.mark.asyncio
async def test_process_calls_prompt_builder_before_llm() -> None:
    """F3-1: the prompt builder is invoked BEFORE the LLM call.

    Verifies the call ordering: prompt builder runs first (its
    output is passed as ``system_prompt`` to the LLM). We
    instrument both with a counter and check the ordering.
    """
    call_order: list[str] = []

    class _OrderLLM(MockLLMClient):
        async def generate_with_state_contract(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            call_order.append("llm")
            return await super().generate_with_state_contract(*args, **kwargs)

    class _OrderBuilder:
        def __init__(self) -> None:
            self.calls = 0

        async def build(self, character_id: str, current_state: Any, action_context: Any) -> str:
            self.calls += 1
            call_order.append("builder")
            return "BUILDER_PROMPT"

    builder = _OrderBuilder()
    llm = _OrderLLM(canned_response=('{"narrative": "hi", "state_mutations": null}'))
    proc = ActionProcessor(
        llm_client=llm,
        memory_palace=None,
        turn_system=InMemoryTurnSystem(),
        state_machine=None,
        prompt_builder=builder,
    )
    result = await proc.process("char_demo_player", "look")
    assert result["status"] == "processed"
    # Builder was called once, before the LLM.
    assert call_order == ["builder", "llm"]
    assert builder.calls == 1


@pytest.mark.asyncio
async def test_process_persists_valid_mutation() -> None:
    """F3-2: a valid LLM-emitted StateMutation is applied to the state machine.

    The processor's ``state_machine.apply_mutations`` must be
    called with the validated ``StateMutation`` instance, and the
    response's ``mutation`` field must echo the validated payload.
    """
    from backend.state_machine import (
        SemanticState,
        SemanticStateMachine,
    )

    sm = SemanticStateMachine()
    # Pre-register a state for the character so we can see the
    # add/remove in action.
    sm.register(SemanticState(character_id="char_alice", tags=["健康"]))

    canned_with_mutation = (
        '{"narrative": "Alice takes a hit.", '
        '"state_mutations": {'
        '"target": "self", '
        '"character_id": "char_alice", '
        '"add_state": ["右手骨折"], '
        '"remove_state": ["健康"], '
        '"reason": "Alice falls and breaks her right arm."}}'
    )
    llm = MockLLMClient(canned_response=canned_with_mutation)
    proc = ActionProcessor(
        llm_client=llm,
        memory_palace=None,
        turn_system=InMemoryTurnSystem(),
        state_machine=sm,
        prompt_builder=None,
    )

    result = await proc.process("char_alice", "attack", "goblin")
    assert result["status"] == "processed"
    assert result["narrative"] == "Alice takes a hit."

    # The mutation was validated and applied: the character's state
    # now contains "右手骨折" and no longer contains "健康".
    state_after = sm.get("char_alice")
    assert state_after is not None
    assert "右手骨折" in state_after.tags
    assert "健康" not in state_after.tags

    # The response's ``mutation`` field echoes the validated payload.
    assert result["mutation"] is not None
    assert result["mutation"]["add_state"] == ["右手骨折"]
    assert result["mutation"]["remove_state"] == ["健康"]
    assert result["mutation_error"] is None


@pytest.mark.asyncio
async def test_process_drops_invalid_mutation() -> None:
    """F3-3: a malformed LLM mutation is dropped, no crash, narrative returned.

    The LLM emits a ``state_mutations`` block that violates F1
    defense D2 (extra field, oversized tag, non-CJK char). The
    processor must:
      * not crash
      * return the narrative
      * set ``mutation=None`` and ``mutation_error`` to a short reason
      * NOT modify the character's state
    """
    from backend.state_machine import (
        SemanticState,
        SemanticStateMachine,
    )

    sm = SemanticStateMachine()
    sm.register(SemanticState(character_id="char_bob", tags=["健康"]))

    # Extra field ``bogus`` violates extra="forbid" on StateMutation.
    invalid_canned = (
        '{"narrative": "Bob stumbles.", '
        '"state_mutations": {'
        '"target": "self", '
        '"character_id": "char_bob", '
        '"add_state": ["右手骨折"], '
        '"remove_state": ["健康"], '
        '"reason": "test", '
        '"bogus": "extra field not allowed"}}'
    )
    llm = MockLLMClient(canned_response=invalid_canned)
    proc = ActionProcessor(
        llm_client=llm,
        memory_palace=None,
        turn_system=InMemoryTurnSystem(),
        state_machine=sm,
        prompt_builder=None,
    )

    result = await proc.process("char_bob", "walk")
    # No crash, narrative returned.
    assert result["status"] == "processed"
    assert result["narrative"] == "Bob stumbles."
    # Mutation was rejected.
    assert result["mutation"] is None
    assert result["mutation_error"] is not None
    assert "validation_failed" in result["mutation_error"]
    # The character's state is UNCHANGED.
    state_after = sm.get("char_bob")
    assert state_after is not None
    assert state_after.tags == ["健康"], f"state must be unchanged, got {state_after.tags!r}"


@pytest.mark.asyncio
async def test_process_feeds_memory_palace_with_state_anchor() -> None:
    """F3-4: after a process() call, the state machine feeds Memory Palace.

    F1 defense D3: the feed uses ``state=<tags>;narrative=<truncated>``
    with a 127-char cap, NOT the raw narrative. We verify by
    hooking the state machine's memory palace and asserting the
    ``remember()`` call received the state-anchored feed.
    """
    from unittest.mock import AsyncMock as _AM

    from backend.state_machine import (
        SemanticState,
        SemanticStateMachine,
    )

    sm = SemanticStateMachine()
    sm.register(SemanticState(character_id="carol", tags=["健康", "平靜"]))

    palace_mock = _AM()
    remember_mock = _AM(return_value="mem_abc")
    palace_mock.remember = remember_mock

    sm._memory_palace = palace_mock  # type: ignore[attr-defined]

    canned = '{"narrative": "Carol walks into the forest.", ' '"state_mutations": null}'
    llm = MockLLMClient(canned_response=canned)
    proc = ActionProcessor(
        llm_client=llm,
        memory_palace=None,
        turn_system=InMemoryTurnSystem(),
        state_machine=sm,
        prompt_builder=None,
    )

    result = await proc.process("carol", "walk", "into the forest")
    assert result["status"] == "processed"
    # The state machine's feed_memory_palace was awaited with the
    # state-anchored feed. The mock palace's remember() received
    # a content string starting with ``state=``.
    remember_mock.assert_awaited_once()
    kwargs = remember_mock.await_args.kwargs
    assert kwargs["character_id"] == "carol"
    feed = kwargs["content"]
    assert feed.startswith("state="), f"feed must start with state= anchor, got {feed!r}"
    # Bounded length (F1 D3 cap: 127 chars).
    assert len(feed) <= 127, f"feed length {len(feed)} exceeds 127-char cap: {feed!r}"
    # The state tags appear in the anchor.
    assert "健康" in feed or "平靜" in feed
    # The narrative appears in the feed (truncated to 200 chars).
    assert "Carol walks" in feed
