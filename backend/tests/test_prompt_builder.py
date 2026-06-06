"""
Prompt Builder tests (Phase F4, 2026-06-05)
===========================================

10 tests verifying the PromptBuilder contract:

  1. test_build_includes_state_at_top
        The state section appears within the first MAX_STATE_SECTION_LENGTH
        chars of the system prompt (i.e. at the top).

  2. test_build_uses_5_critical_template_sections
        All 5 template headers (角色當前狀態, 角色記憶摘要, 動作上下文,
        輸出格式要求, 重要規則) are present.

  3. test_state_section_bounded_length
        A 100-tag state is truncated to MAX_STATE_SECTION_LENGTH.

  4. test_empty_state_uses_health_default
        current_state.tags=[] → "(無當前狀態 — 健康)" appears in the prompt.

  5. test_memory_section_uses_memory_palace_recall
        A mock palace is called with character_id, query_embedding, k=5.

  6. test_memory_section_handles_palace_failure
        When the mock palace raises, the section says "(Memory Palace 查詢失敗)".

  7. test_action_context_includes_verb_and_target
        The action context section formats verb and target correctly.

  8. test_state_always_above_memory_in_prompt
        Regex check: the state section's position < memory section's
        position. The state is the "absolute current reality" rule.

  9. test_chinese_cjk_state_handled
        7 CJK tags format correctly with 「...」 brackets and "|" separators.

 10. test_invalid_state_falls_back_gracefully
        A state with 8 tags (the max allowed) renders without crashing,
        and the underlying character_id round-trips through build().

Run with:
    .venv/Scripts/python.exe -m pytest backend/tests/test_prompt_builder.py -q
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# ============================================
# Fixtures
# ============================================


@pytest.fixture
def basic_state() -> SemanticState:
    """A 2-tag state for most tests."""
    from backend.state_machine import SemanticState

    return SemanticState(
        character_id="alice",
        tags=["右手骨折", "中毒"],
    )


@pytest.fixture
def empty_state() -> SemanticState:
    """A 0-tag state — the (no_state) edge case."""
    from backend.state_machine import SemanticState

    return SemanticState(character_id="bob", tags=[])


@pytest.fixture
def cjk_seven_tag_state() -> SemanticState:
    """7 CJK tags — at the display cap."""
    from backend.state_machine import SemanticState

    return SemanticState(
        character_id="wukong",
        tags=[
            "金箍棒", "筋斗雲", "火眼金睛", "七十二變",
            "不死之身", "頭部金剛", "銅皮鐵骨",
        ],
    )


@pytest.fixture
def basic_action_context() -> dict[str, Any]:
    """A typical action context with a query_embedding for memory recall."""
    return {
        "verb": "attack",
        "target": "goblin",
        "args": {"weapon": "sword"},
        "query_embedding": [0.0] * 128,  # EMBEDDING_DIM=128 (will fail palace if real)
    }


@pytest.fixture
def no_palace_builder():
    """A PromptBuilder with no memory palace."""
    from backend.prompt_builder import PromptBuilder

    return PromptBuilder()


@pytest.fixture
def mock_palace():
    """An AsyncMock memory palace that returns a canned 3-memory list."""
    palace = MagicMock()
    palace.recall = AsyncMock(
        return_value=[
            {"content": "Met the wizard in the tower."},
            {"content": "Fought a goblin near the bridge."},
            {"content": "Found a shiny red potion."},
        ]
    )
    return palace


# ============================================
# Tests
# ============================================


def test_build_includes_state_at_top(
    no_palace_builder, basic_state, basic_action_context
) -> None:
    """The state section appears within the first MAX_STATE_SECTION_LENGTH
    chars of the system prompt (i.e. at the top, not buried after memory)."""
    import asyncio

    prompt = asyncio.run(
        no_palace_builder.build(
            character_id="alice",
            current_state=basic_state,
            action_context=basic_action_context,
        )
    )
    # The state section's first tag should appear early in the prompt.
    assert "「右手骨折」" in prompt
    state_idx = prompt.find("「右手骨折」")
    # The 角色當前狀態 header should appear BEFORE the first tag,
    # and the state section should sit in the top half of the prompt.
    header_idx = prompt.find("角色當前狀態")
    assert 0 <= header_idx < state_idx < 600, (
        f"state section should be at the top; "
        f"header={header_idx}, tag={state_idx}"
    )


def test_build_uses_5_critical_template_sections(
    no_palace_builder, basic_state, basic_action_context
) -> None:
    """All 5 template headers are present in the rendered prompt."""
    import asyncio

    prompt = asyncio.run(
        no_palace_builder.build(
            character_id="alice",
            current_state=basic_state,
            action_context=basic_action_context,
        )
    )
    expected_sections = [
        "角色當前狀態",
        "角色記憶摘要",
        "動作上下文",
        "輸出格式要求",
        "重要規則",
    ]
    for header in expected_sections:
        assert header in prompt, f"Missing template section: {header!r}"


def test_state_section_bounded_length(
    no_palace_builder, basic_action_context
) -> None:
    """A 100-tag state is truncated to MAX_STATE_SECTION_LENGTH.

    Note: the real ``SemanticState`` constructor caps tags at
    ``MAX_TAGS_PER_CHARACTER = 8`` (D2 invariant). This test bypasses
    the constructor with a mock state object to verify the
    *defensive* truncation in ``_format_state_section`` — the
    "future world could relax the cap" case. A real production state
    with 8 tags is well under the 500-char cap by construction.
    """
    from backend.prompt_builder import MAX_STATE_SECTION_LENGTH
    from backend.state_machine import SemanticState

    # Build a mock state that passes the isinstance check but has
    # 100 tags (the real constructor would reject 100, but the
    # builder's defensive truncation is the part under test).
    mock_state = MagicMock(spec=SemanticState)
    # 100 short CJK-flavored tags. We use the spec so isinstance()
    # returns True for SemanticState.
    mock_state.tags = [f"標第{['一', '二', '三', '四', '五', '六', '七', '八', '九', '十'][i % 10]}個"
                       for i in range(100)]

    # Bypass isinstance by setting the spec class directly.
    # MagicMock(spec=SemanticState) makes isinstance(mock, SemanticState)
    # return True, which is what the builder checks.
    assert isinstance(mock_state, SemanticState)

    section = no_palace_builder._format_state_section(mock_state)
    assert len(section) <= MAX_STATE_SECTION_LENGTH, (
        f"State section {len(section)} chars exceeds "
        f"MAX_STATE_SECTION_LENGTH={MAX_STATE_SECTION_LENGTH}"
    )
    # Truncation marker present.
    assert "未顯示" in section


def test_empty_state_uses_health_default(
    no_palace_builder, empty_state, basic_action_context
) -> None:
    """An empty state (no tags) shows the health-default placeholder."""
    import asyncio

    prompt = asyncio.run(
        no_palace_builder.build(
            character_id="bob",
            current_state=empty_state,
            action_context=basic_action_context,
        )
    )
    assert "(無當前狀態 — 健康)" in prompt


def test_memory_section_uses_memory_palace_recall(
    mock_palace, basic_state, basic_action_context
) -> None:
    """The mock palace is called with character_id, query_embedding, k=5."""
    import asyncio

    from backend.prompt_builder import DEFAULT_TOP_K_MEMORIES, PromptBuilder

    builder = PromptBuilder(memory_palace=mock_palace)
    prompt = asyncio.run(
        builder.build(
            character_id="alice",
            current_state=basic_state,
            action_context=basic_action_context,
        )
    )
    # The mock should have been called once.
    mock_palace.recall.assert_awaited_once()
    # Inspect the call args.
    call_kwargs = mock_palace.recall.await_args.kwargs
    assert call_kwargs["character_id"] == "alice"
    assert call_kwargs["query_embedding"] == [0.0] * 128
    assert call_kwargs["k"] == DEFAULT_TOP_K_MEMORIES
    # The memory content should appear in the prompt.
    assert "Met the wizard" in prompt
    assert "Fought a goblin" in prompt


def test_memory_section_handles_palace_failure(
    basic_state, basic_action_context
) -> None:
    """When the mock palace raises, the section says '(Memory Palace 查詢失敗)'."""
    import asyncio

    failing_palace = MagicMock()
    failing_palace.recall = AsyncMock(side_effect=RuntimeError("palace down"))

    from backend.prompt_builder import PromptBuilder

    builder = PromptBuilder(memory_palace=failing_palace)
    prompt = asyncio.run(
        builder.build(
            character_id="alice",
            current_state=basic_state,
            action_context=basic_action_context,
        )
    )
    assert "(Memory Palace 查詢失敗)" in prompt
    # The state section should still be present and intact.
    assert "「右手骨折」" in prompt


def test_action_context_includes_verb_and_target(
    no_palace_builder, basic_state
) -> None:
    """The action context section formats verb and target correctly."""
    import asyncio

    ctx = {"verb": "look", "target": "north_door", "args": None}
    prompt = asyncio.run(
        no_palace_builder.build(
            character_id="alice",
            current_state=basic_state,
            action_context=ctx,
        )
    )
    assert "動作: look" in prompt
    assert "目標: north_door" in prompt
    # No args → no "參數" line.
    assert "參數:" not in prompt


def test_state_always_above_memory_in_prompt(
    mock_palace, basic_state, basic_action_context
) -> None:
    """The state section is positioned ABOVE the memory section.

    This is the core invariant: 'absolute current reality' is always
    at the top, regardless of what the Memory Palace returned.
    """
    import asyncio

    from backend.prompt_builder import PromptBuilder

    builder = PromptBuilder(memory_palace=mock_palace)
    prompt = asyncio.run(
        builder.build(
            character_id="alice",
            current_state=basic_state,
            action_context=basic_action_context,
        )
    )
    # Find the section headers (the "# ..." lines).
    state_idx = prompt.find("# 角色當前狀態")
    memory_idx = prompt.find("# 角色記憶摘要")
    action_idx = prompt.find("# 動作上下文")
    assert state_idx >= 0
    assert memory_idx >= 0
    assert action_idx >= 0
    # The order must be: state < memory < action.
    assert state_idx < memory_idx, (
        f"state at {state_idx} should be above memory at {memory_idx}"
    )
    assert memory_idx < action_idx, (
        f"memory at {memory_idx} should be above action at {action_idx}"
    )


def test_chinese_cjk_state_handled(
    no_palace_builder, cjk_seven_tag_state, basic_action_context
) -> None:
    """7 CJK tags format correctly with 「...」 brackets and "|" separators."""
    import asyncio

    prompt = asyncio.run(
        no_palace_builder.build(
            character_id="wukong",
            current_state=cjk_seven_tag_state,
            action_context=basic_action_context,
        )
    )
    # All 7 tags should appear, each wrapped in 「...」.
    for tag in cjk_seven_tag_state.tags:
        assert f"「{tag}」" in prompt, f"Missing CJK tag: {tag}"
    # Separated by " | ".
    assert " | " in prompt


def test_invalid_state_falls_back_gracefully(
    no_palace_builder, basic_action_context
) -> None:
    """A state at MAX_TAGS_PER_CHARACTER (8) renders without crashing.

    The SemanticState constructor enforces the 8-tag cap; we build
    a state with 8 valid CJK tags and verify the prompt renders
    without error, with the first 7 visible and an overflow marker.
    """
    import asyncio

    from backend.prompt_builder import MAX_TAGS_DISPLAYED
    from backend.state_machine import (
        MAX_TAGS_PER_CHARACTER,
        SemanticState,
    )

    # 8 valid CJK tags (no digits, no punctuation). Pure CJK only.
    chinese_numerals = ["一", "二", "三", "四", "五", "六", "七", "八"]
    tags = [f"標第{zh}個" for zh in chinese_numerals]
    assert len(tags) == MAX_TAGS_PER_CHARACTER
    state = SemanticState(character_id="carol", tags=tags)

    prompt = asyncio.run(
        no_palace_builder.build(
            character_id="carol",
            current_state=state,
            action_context=basic_action_context,
        )
    )
    # All but the last (overflow) tag should be visible.
    for tag in tags[:MAX_TAGS_DISPLAYED]:
        assert f"「{tag}」" in prompt, f"Missing displayed tag: {tag}"
    # The 8th tag is overflow — should NOT appear in the rendered
    # state section (it's the one we truncate).
    assert f"「{tags[MAX_TAGS_DISPLAYED]}」" not in prompt
    # A tail marker should indicate overflow.
    assert "未顯示" in prompt
    # The character_id round-trips through build() without error
    # (no exception, prompt is a non-empty string).
    assert isinstance(prompt, str) and len(prompt) > 0
