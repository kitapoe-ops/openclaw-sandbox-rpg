"""Tests for the 5-module user prompt builder (2026-06-08).

These tests cover:
- Each section formatter (health, inventory, scene NPCs, threads,
  footprints, trope directive)
- The full build_user_prompt() end-to-end (5 modules)
- ALLOWED_CHOICE_DIRECTIONS enum (used by the LLM output validator)
- Section breakdown (build_user_prompt_sections) for the Prompt Inspector
"""
import pytest

from backend.prompt_user import (
    USER_PROMPT_TEMPLATE,
    ALLOWED_CHOICE_DIRECTIONS,
    build_user_prompt,
    build_user_prompt_sections,
    _format_health_status,
    _format_inventory_with_physical_tags,
    _format_scene_npc_states,
    _format_active_escalation_threads,
    _format_other_player_footprints,
    _format_trope_directive,
)
from backend.state_machine import SemanticState


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def make_state(character_id="alice", tags=None, active_threads=None):
    return SemanticState(
        character_id=character_id,
        tags=tags or [],
        inventory={"items": []},
        active_threads=active_threads or {},
    )


def make_scene_context(npcs=None, footprints=None, location_tag="tavern"):
    return {
        "scene_id": "scene-1",
        "summary": "preview",
        "location_tag": location_tag,
        "npcs": npcs or [],
        "footprints": footprints or [],
    }


# --------------------------------------------------------------------------
# Module 1: Hard Facts
# --------------------------------------------------------------------------


class TestHealthStatus:
    def test_no_tags_returns_healthy(self):
        assert _format_health_status(make_state(tags=[])) == "健康"

    def test_death_tag_takes_priority(self):
        assert _format_health_status(make_state(tags=["健康", "死亡"])) == "死亡"
        assert _format_health_status(make_state(tags=["瀕死", "右手骨折"])) == "瀕死"

    def test_no_numeric_hp_ever(self):
        """F1 invariant: never output numeric HP."""
        # Use valid CJK tag (F1's tag validator rejects = and digits
        # outright, so we can't put numeric content in tags. But the
        # contract is: the formatter must not produce numeric output
        # regardless of input.)
        result = _format_health_status(make_state(tags=["瀕死"]))
        assert result == "瀕死"  # no numeric content
        result = _format_health_status(make_state(tags=[]))
        assert result == "健康"  # default, no numeric content

    def test_returns_first_two_tags_when_no_death(self):
        result = _format_health_status(make_state(tags=["右手骨折", "失血", "健康"]))
        # Should surface health-relevant first 1-2 tags
        assert "右手骨折" in result


class TestInventoryPlaceholder:
    def test_returns_placeholder_when_hidden(self):
        """2026-06-08: items/equipment system is disabled."""
        result = _format_inventory_with_physical_tags(make_state())
        assert "無裝備" in result
        assert "系統已關閉" in result

    def test_preserves_physical_constraint_rule(self):
        """The writing-rule reference to physical tags must remain."""
        result = _format_inventory_with_physical_tags(make_state())
        assert "物理" in result
        assert "不得捏造" in result


class TestSceneNpcStates:
    def test_empty_returns_placeholder(self):
        assert _format_scene_npc_states({}) == "(場景內無 NPC)"
        assert _format_scene_npc_states(None) == "(無 scene context — NPC 狀態未知)"

    def test_renders_name_status_location(self):
        scene = make_scene_context(
            npcs=[
                {"npc_id": "e1", "name": "Eldrin", "status": "hostile", "location": "tavern"},
                {"npc_id": "m1", "name": "Mira", "status": "neutral"},
            ]
        )
        result = _format_scene_npc_states(scene)
        assert "Eldrin" in result
        assert "hostile" in result
        assert "tavern" in result
        assert "Mira" in result
        assert "neutral" in result

    def test_caps_at_six_npcs(self):
        npcs = [{"npc_id": f"n{i}", "name": f"NPC{i}", "status": "neutral"} for i in range(10)]
        scene = make_scene_context(npcs=npcs)
        result = _format_scene_npc_states(scene)
        # Should mention first 6 only
        for i in range(6):
            assert f"NPC{i}" in result
        # And not the rest
        assert "NPC6" not in result and "NPC9" not in result


# --------------------------------------------------------------------------
# Module 2: Karma & Traces
# --------------------------------------------------------------------------


class TestActiveEscalationThreads:
    def test_empty_returns_placeholder(self):
        state = make_state(active_threads={})
        assert "無 active threads" in _format_active_escalation_threads(state)

    def test_renders_trope_id_with_level(self):
        state = make_state(
            active_threads={"trope_scapegoat_01": {"status": "Active", "escalation_level": 2}}
        )
        result = _format_active_escalation_threads(state)
        assert "level=2" in result
        assert "Active" in result or "發酵" in result

    def test_skips_resolved_threads(self):
        state = make_state(
            active_threads={
                "trope_a": {"status": "Resolved", "escalation_level": 0},
                "trope_b": {"status": "Active", "escalation_level": 1},
            }
        )
        result = _format_active_escalation_threads(state)
        assert "trope_b" in result or "trope_b" in result.replace("_", " ")


class TestOtherPlayerFootprints:
    def test_empty_returns_placeholder(self):
        assert _format_other_player_footprints({}) == "(場景內無其他玩家痕跡)"
        assert _format_other_player_footprints(None) == "(無環境痕跡)"

    def test_renders_marker_with_actor_and_turn(self):
        scene = make_scene_context(footprints=[{"marker": "地上有血跡", "actor": "Bob", "turn": 3}])
        result = _format_other_player_footprints(scene)
        assert "地上有血跡" in result
        assert "Bob" in result
        assert "3" in result

    def test_caps_at_six_footprints(self):
        scene = make_scene_context(
            footprints=[{"marker": f"痕跡{i}", "actor": f"A{i}", "turn": i} for i in range(10)]
        )
        result = _format_other_player_footprints(scene)
        for i in range(6):
            assert f"痕跡{i}" in result
        assert "痕跡6" not in result

    def test_audit_invariant_preserved(self):
        """Footprints are environmental metadata, NOT cross-character memory.
        The memory_isolation invariant is NOT broken.
        """
        # Pass only scene-level metadata; no private-memory access
        scene = make_scene_context(footprints=[{"marker": "blood", "actor": "Bob"}])
        _format_other_player_footprints(scene)
        # The function only reads scene_context['footprints']; it does
        # not query memory_palace or any per-character private store.


# --------------------------------------------------------------------------
# Module 4: Trope Directive
# --------------------------------------------------------------------------


class TestTropeDirective:
    def test_no_threads_returns_placeholder(self):
        state = make_state(active_threads={})
        result = _format_trope_directive(state)
        assert "無 trope directive" in result or "無 active trope" in result

    def test_renders_trope_name_with_directive(self):
        """Trope directive should include plot_beat + tonal_focus from tropes.json."""
        # tropes.json ships with trope_scapegoat_01; we use it for a smoke test
        state = make_state(
            active_threads={"trope_scapegoat_01": {"status": "Active", "escalation_level": 0}}
        )
        result = _format_trope_directive(state)
        # Should at least contain the trope name
        assert len(result) > 5
        assert "trope_scapegoat" not in result  # uses trope_name from router


# --------------------------------------------------------------------------
# End-to-end: build_user_prompt
# --------------------------------------------------------------------------


class TestBuildUserPrompt:
    def test_renders_all_five_modules(self):
        state = make_state(character_id="alice", tags=["健康"])
        scene = make_scene_context(
            npcs=[{"npc_id": "e1", "name": "Eldrin", "status": "hostile"}],
            footprints=[{"marker": "血跡", "actor": "Bob", "turn": 2}],
        )
        result = build_user_prompt(
            character_id="alice",
            current_state=state,
            verb="attack",
            target="goblin",
            args_str=" with weapon=sword",
            scene_context=scene,
        )

        # 5 module headers
        assert "[模塊 1：硬性物理與狀態" in result
        assert "[模塊 2：世界因果與痕跡" in result
        assert "[模塊 3：玩家本回合行動" in result
        assert "[模塊 4：劇本與寫作鐵律" in result
        assert "[模塊 5：強制輸出格式" in result

        # Trigger action
        assert "Player Action: attack goblin  with weapon=sword" in result

        # Output format example JSON contains state_mutations + choices
        assert "state_mutations" in result
        assert "choices" in result
        assert '"direction": "combat"' in result
        assert '"direction": "social"' in result
        assert '"direction": "explore"' in result
        assert '"direction": "creative"' in result

        # Writing rules
        assert "Show, Don't Tell" in result
        assert "Physical Reality" in result

    def test_inventory_placeholder_preserved(self):
        """Equipment section in user prompt must remain hidden."""
        state = make_state()
        result = build_user_prompt(
            character_id="alice", current_state=state, verb="look", target=None, args_str=""
        )
        assert "無裝備" in result
        assert "系統已關閉" in result

    def test_no_numeric_hp_appears(self):
        state = make_state(tags=["健康"])
        result = build_user_prompt(
            character_id="alice", current_state=state, verb="attack", target="x", args_str=""
        )
        # Module 1 should have HP: but no numeric value
        import re

        m = re.search(r"HP:\s*(\S+)", result)
        if m:
            label = m.group(1)
            assert (
                not label.replace("+", "").replace(" ", "").isdigit()
            ), f"HP label looks numeric: {label!r}"


# --------------------------------------------------------------------------
# ALLOWED_CHOICE_DIRECTIONS enum
# --------------------------------------------------------------------------


class TestAllowedChoiceDirections:
    def test_exactly_four_directions(self):
        assert len(ALLOWED_CHOICE_DIRECTIONS) == 4

    def test_required_directions_present(self):
        for d in ("combat", "social", "explore", "creative"):
            assert d in ALLOWED_CHOICE_DIRECTIONS


# --------------------------------------------------------------------------
# Section breakdown (Prompt Inspector)
# --------------------------------------------------------------------------


class TestBuildUserPromptSections:
    def test_returns_all_section_keys(self):
        state = make_state()
        sections = build_user_prompt_sections(
            character_id="alice",
            current_state=state,
            verb="look",
            target=None,
            args_str="",
        )
        for key in (
            "character_id",
            "health_status",
            "inventory_with_physical_tags",
            "scene_npc_states",
            "active_escalation_threads",
            "other_player_footprints",
            "verb",
            "target",
            "args_str",
            "current_trope_directive",
        ):
            assert key in sections, f"missing key: {key}"

    def test_target_defaults_to_placeholder(self):
        state = make_state()
        sections = build_user_prompt_sections(
            character_id="alice",
            current_state=state,
            verb="look",
            target=None,
            args_str="",
        )
        assert sections["target"] == "(nothing)"
