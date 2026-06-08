"""End-to-end tests for the 5-module user prompt + choices pipeline (2026-06-08).

These tests wire a MockLLMClient to the ActionProcessor and verify that
the full 5-module user prompt is constructed, the MockLLM response
(narrative + state_mutations + choices) is parsed, and the final
``handle()`` response carries the ``choices`` field.

The tests use the in-memory test mode (no DB writes, no LLM network,
no R1 audit) so they are safe to run in CI without infrastructure.
"""
import json
import pytest

from backend.api.action_processor import (
    ActionProcessor,
    _validate_and_extract_choices,
    ALLOWED_VERBS,
)
from backend.llm_client import MockLLMClient
from backend.state_machine import SemanticState, SemanticStateMachine


# --------------------------------------------------------------------------
# Helper: build a minimal ActionProcessor wired to a MockLLMClient
# --------------------------------------------------------------------------


def make_processor_with_mock(mock_canned: str | None = None) -> ActionProcessor:
    """Build an ActionProcessor that uses MockLLMClient for all calls.

    No DB, no R1 audit, no turn system, no prompt builder wired —
    enough to exercise the user-prompt construction + LLM response
    parsing + _validate_and_extract_choices path.
    """
    mock = MockLLMClient(canned_response=mock_canned)
    state_machine = SemanticStateMachine()
    return ActionProcessor(
        llm_client=mock,
        state_machine=state_machine,
        prompt_builder=None,  # exercises the inline fallback system prompt
    )


# A canned response that includes all 4 choices + a valid state_mutations
SAMPLE_5MODULE_RESPONSE = json.dumps(
    {
        "narrative": "你凝視遠方，感受到風中帶有陌生的味道。",
        "state_mutations": {
            "target": "alice",
            "add_state": ["警覺"],
            "remove_state": [],
            "reason": "玩家進入警戒狀態",
        },
        "choices": [
            {"direction": "combat", "vignette": "拔劍備戰"},
            {"direction": "social", "vignette": "向神秘人打招呼"},
            {"direction": "explore", "vignette": "悄悄繞路"},
            {"direction": "creative", "vignette": "用繩子製作陷阱"},
        ],
    }
)


# --------------------------------------------------------------------------
# Test: 5-module prompt structure
# --------------------------------------------------------------------------


class Test5ModulePromptStructure:
    """The LLM's user_message should be the 5-module structure."""

    @pytest.mark.asyncio
    async def test_user_message_contains_5_module_headers(self):
        from backend.prompt_user import build_user_prompt
        from backend.state_machine import SemanticState

        state = SemanticState(character_id="alice", tags=["健康"])
        prompt = build_user_prompt(
            character_id="alice",
            current_state=state,
            verb="look",
            target=None,
            args_str="",
        )

        # All 5 module headers
        for i in range(1, 6):
            assert f"### [模塊 {i}：" in prompt, f"missing module {i}"

    def test_user_message_has_correct_field_placeholders(self):
        from backend.prompt_user import build_user_prompt
        from backend.state_machine import SemanticState

        state = SemanticState(character_id="bob", tags=["健康"])
        prompt = build_user_prompt(
            character_id="bob",
            current_state=state,
            verb="attack",
            target="goblin",
            args_str=" with weapon=sword",
        )

        assert "Character: bob" in prompt
        assert "Player Action: attack goblin  with weapon=sword" in prompt
        assert "(無裝備 — 系統已關閉" in prompt
        assert "scene_npc_states" not in prompt or "Scene NPCs:" in prompt


# --------------------------------------------------------------------------
# Test: _validate_and_extract_choices
# --------------------------------------------------------------------------


class TestValidateAndExtractChoices:
    """The action-processor helper that turns LLM output into UI choices."""

    def test_accepts_well_formed_choices(self):
        choices = _validate_and_extract_choices(
            [
                {"direction": "combat", "vignette": "拔劍"},
                {"direction": "social", "vignette": "對話"},
                {"direction": "explore", "vignette": "探索"},
                {"direction": "creative", "vignette": "製作"},
            ]
        )
        assert len(choices) == 4
        for c in choices:
            assert "direction" in c
            assert "vignette" in c

    def test_drops_unknown_direction(self):
        choices = _validate_and_extract_choices(
            [
                {"direction": "combat", "vignette": "拔劍"},
                {"direction": "fly", "vignette": "飛行"},  # not in allowed
            ]
        )
        assert len(choices) == 1
        assert choices[0]["direction"] == "combat"

    def test_drops_empty_vignette(self):
        choices = _validate_and_extract_choices(
            [
                {"direction": "combat", "vignette": ""},
                {"direction": "social", "vignette": "   "},
                {"direction": "explore", "vignette": "ok"},
            ]
        )
        assert len(choices) == 1
        assert choices[0]["direction"] == "explore"

    def test_drops_non_list_input(self):
        assert _validate_and_extract_choices(None) == []
        assert _validate_and_extract_choices("not a list") == []
        assert _validate_and_extract_choices({}) == []

    def test_caps_at_four(self):
        choices = _validate_and_extract_choices(
            [{"direction": "combat", "vignette": f"選項{i}描述"} for i in range(10)]
        )
        assert len(choices) == 4
        # First 4 should be preserved (in order)
        for i, c in enumerate(choices):
            assert c["vignette"] == f"選項{i}描述"

    def test_soft_drops_high_numeric_content(self):
        """Per Module 5: 'Risks ... 不可提供數字'. Soft-drop entries
        whose character-level digit ratio exceeds 50% (for vignettes
        of length >= 5 chars). Short tags like 'v1' are preserved."""
        choices = _validate_and_extract_choices(
            [
                {"direction": "combat", "vignette": "v1"},  # short, kept
                {"direction": "social", "vignette": "1234567890abcd"},  # 10/14 digits → dropped
                {"direction": "explore", "vignette": "走向遠方"},
            ]
        )
        directions = [c["direction"] for c in choices]
        assert "combat" in directions
        assert "explore" in directions
        # The long numeric-heavy vignette should be dropped
        assert "social" not in directions

    def test_preserves_order(self):
        choices = _validate_and_extract_choices(
            [
                {"direction": "explore", "vignette": "探索"},
                {"direction": "combat", "vignette": "戰鬥"},
            ]
        )
        assert choices[0]["direction"] == "explore"
        assert choices[1]["direction"] == "combat"


# --------------------------------------------------------------------------
# Test: MockLLMClient passes through choices
# --------------------------------------------------------------------------


class TestMockLLMClientChoicesPassthrough:
    """The mock's ``generate_with_state_contract`` must surface the LLM's
    ``choices`` array in the result dict (so the action processor's
    ``_validate_and_extract_choices`` can pick them up)."""

    @pytest.mark.asyncio
    async def test_mock_default_canned_response_has_choices(self):
        mock = MockLLMClient()
        result = await mock.generate_with_state_contract(
            system_prompt="...",
            user_message="...",
            current_state=[],
        )
        assert "choices" in result
        assert isinstance(result["choices"], list)
        # Default canned has 4 choices
        assert len(result["choices"]) == 4

    @pytest.mark.asyncio
    async def test_mock_passes_through_custom_choices(self):
        custom = json.dumps(
            {
                "narrative": "narr",
                "state_mutations": None,
                "choices": [
                    {"direction": "combat", "vignette": "v1"},
                    {"direction": "social", "vignette": "v2"},
                ],
            }
        )
        mock = MockLLMClient(canned_response=custom)
        result = await mock.generate_with_state_contract(
            system_prompt="",
            user_message="",
            current_state=[],
        )
        assert len(result["choices"]) == 2
        assert result["choices"][0]["vignette"] == "v1"

    @pytest.mark.asyncio
    async def test_mock_handles_missing_choices(self):
        no_choices = json.dumps({"narrative": "narr", "state_mutations": None})
        mock = MockLLMClient(canned_response=no_choices)
        result = await mock.generate_with_state_contract(
            system_prompt="",
            user_message="",
            current_state=[],
        )
        # No choices in canned → mock returns empty list (not None,
        # not missing key — keeps the action processor's contract simple)
        assert "choices" in result
        assert result["choices"] == []

    @pytest.mark.asyncio
    async def test_mock_filters_non_dict_choices(self):
        mixed = json.dumps(
            {
                "narrative": "narr",
                "state_mutations": None,
                "choices": [
                    {"direction": "combat", "vignette": "v1"},
                    "not a dict",
                    42,
                    None,
                ],
            }
        )
        mock = MockLLMClient(canned_response=mixed)
        result = await mock.generate_with_state_contract(
            system_prompt="",
            user_message="",
            current_state=[],
        )
        assert len(result["choices"]) == 1
        assert result["choices"][0]["direction"] == "combat"


# --------------------------------------------------------------------------
# Test: ActionProcessor end-to-end with Mock LLM
# --------------------------------------------------------------------------


class TestActionProcessorEndToEnd:
    """Full handle() flow with a MockLLMClient returning 5-module output."""

    @pytest.mark.asyncio
    async def test_handle_returns_choices_from_mock_response(self):
        processor = make_processor_with_mock(SAMPLE_5MODULE_RESPONSE)
        # No DB, no scene context; the action processor should still
        # build a 5-module user prompt, call the mock, and return
        # the parsed choices in the response.
        result = await processor.process(
            character_id="alice",
            verb="look",
            target=None,
            args=None,
        )

        assert result["status"] == "processed"
        assert "narrative" in result
        # 2026-06-08: choices field is present in the response
        assert "choices" in result
        assert len(result["choices"]) == 4
        for c in result["choices"]:
            assert c["direction"] in ALLOWED_VERBS or c["direction"] in (
                "combat",
                "social",
                "explore",
                "creative",
            )

    @pytest.mark.asyncio
    async def test_handle_choices_filter_invalid_directions(self):
        """If the LLM returns a choice with an invalid direction,
        ``_validate_and_extract_choices`` drops it before it reaches
        the response."""
        bad_canned = json.dumps(
            {
                "narrative": "narr",
                "state_mutations": None,
                "choices": [
                    {"direction": "combat", "vignette": "v1"},
                    {"direction": "fly", "vignette": "v2"},  # invalid
                    {"direction": "social", "vignette": "v3"},
                ],
            }
        )
        processor = make_processor_with_mock(bad_canned)
        result = await processor.process(character_id="alice", verb="look")
        assert len(result["choices"]) == 2
        directions = {c["direction"] for c in result["choices"]}
        assert directions == {"combat", "social"}

    @pytest.mark.asyncio
    async def test_handle_empty_choices_returns_empty_list(self):
        no_choices_canned = json.dumps(
            {
                "narrative": "你靜靜地站著。",
                "state_mutations": None,
                "choices": [],
            }
        )
        processor = make_processor_with_mock(no_choices_canned)
        result = await processor.process(character_id="alice", verb="look")
        assert result["choices"] == []

    @pytest.mark.asyncio
    async def test_handle_uses_5module_user_prompt(self):
        """The mock receives the user_message that was rendered by
        ``build_user_prompt``. Verify that by capturing the call arg."""
        # Create a custom mock that records the user_message
        from backend.llm_client import MockLLMClient

        captured: dict[str, str] = {}

        class CapturingMock(MockLLMClient):
            async def generate_with_state_contract(
                self, system_prompt, user_message, current_state, max_retries=2
            ):
                captured["user_message"] = user_message
                captured["system_prompt"] = system_prompt
                # Parse the canned_response and return as a success
                return await super().generate_with_state_contract(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    current_state=current_state,
                    max_retries=max_retries,
                )

        mock = CapturingMock(canned_response=SAMPLE_5MODULE_RESPONSE)
        sm = SemanticStateMachine()
        processor = ActionProcessor(
            llm_client=mock,
            state_machine=sm,
            prompt_builder=None,
        )
        await processor.process(character_id="alice", verb="attack", target="goblin")

        # The captured user_message should be the 5-module structure
        um = captured["user_message"]
        assert "### [模塊 1：" in um
        assert "### [模塊 2：" in um
        assert "### [模塊 3：" in um
        assert "### [模塊 4：" in um
        assert "### [模塊 5：" in um
        assert "Player Action: attack goblin" in um
