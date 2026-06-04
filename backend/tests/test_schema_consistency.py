"""
Schema Consistency Tests
=========================
Validates that the wire format produced by ``StateChangeCalculator`` and
``SceneAgent`` matches the JSON Schema declared in
``docs/SCHEMAS/scene_output.schema.json``.

These tests are the regression net for the R1-14B audit finding: the
calculator used to emit ``{stamina_delta, health_delta, morale_delta}``
integers while the schema (and the frontend) expect nested
``{old, new, reason}`` dicts.

Required test functions (per task spec):
  1. test_state_change_uses_schema_format
  2. test_scene_output_validates_against_schema
  3. test_old_delta_format_rejected_or_converted
  4. test_state_machine_reads_new_format
  5. test_reason_field_populated
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import jsonschema


# Make the repo root importable when pytest is run from another cwd
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.semantic_gradient import (
    StateChange,
    StateChangeCalculator,
)
from backend.scene_agent import (
    SceneAgent,
    _normalize_state_changes,
    SCENE_AGENT_SYSTEM_PROMPT,
)


SCHEMA_PATH = (
    _PROJECT_ROOT / "docs" / "SCHEMAS" / "scene_output.schema.json"
)


@pytest.fixture(scope="module")
def scene_output_schema() -> dict:
    """Load the canonical schema once per module."""
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


# ============================================
# Helpers
# ============================================

def _make_character_state() -> dict:
    """Minimal character state for calculator / scene agent tests."""
    return {
        "character_id": "char_schema_001",
        "name": "SchemaTester",
        "physical": {
            "stamina": "fresh",
            "health": "healthy",
            "active_effects": [],
        },
        "mental": {"morale": "neutral"},
        "inventory": {"items": []},
        "memories": [],
        "relationships": {},
    }


def _make_minimal_scene_output() -> dict:
    """
    Build a complete scene_output dict that conforms to the JSON schema.
    Used to feed into jsonschema.validate() and the state machine.
    """
    return {
        "round": 1,
        "character_id": "char_schema_001",
        "narrative": (
            "你企喺村莊入口，風微微吹過，帶住草嘅香味。遠處有幾間木屋，屋頂 "
            "升起一縷炊煙，似係有人準備晚飯。村口有條石板路，兩旁種滿老榕樹，"
            "樹根盤繞成天然嘅長凳。一位老者坐喺石凳上，閉目養神，膝上放住一頂"
            "舊草帽，帽沿有修補過嘅痕跡。佢身旁有一根青竹拐杖，杖身磨得光亮，"
            "顯然用咗好多年。你聽到風聲、雀仔叫聲，仲有遠處河流嘅低語。空氣入"
            "面有少少泥土同柴火嘅味道，令人覺得安心。黃昏嘅光線慢慢變暗，遠"
            "山嘅輪廓漸漸融入天色。你心知天黑之前要搵個落腳嘅地方，或者向呢"
            "位老者問吓路。風將你嘅衣角吹起，你聞到自己身上一路趕路嘅汗味。"
        ),
        "state_changes": {
            "stamina": {"old": "fresh", "new": "fresh", "reason": "無變化"},
            "health":  {"old": "healthy", "new": "healthy", "reason": "無變化"},
            "morale":  {"old": "neutral", "new": "neutral", "reason": "無變化"},
            "new_status_tags": [],
            "removed_status_tags": [],
            "items_consumed": [],
            "new_memories": [],
            "relationship_changes": [],
        },
        "choices": [
            {
                "id": f"opt_{i:02d}",
                "lore_source": f"location:village_entrance",
                "text": text,
                "intent_category": cat,
                "attitude_options": [
                    {"dimension": "tone", "level": "neutral", "effect": "保持冷靜"},
                    {"dimension": "pace", "level": "deliberate", "effect": "慢慢觀察"},
                ],
            }
            for i, (text, cat) in enumerate([
                ("環顧四周，觀察附近環境嘅變化", "environment"),
                ("沿住石板路向前行，緩緩入村", "environment"),
                ("向坐喺石凳嘅老者打個招呼問好", "npc_interaction"),
                ("停低腳步，整理一下背包入面嘅物品", "item_interaction"),
            ])
        ],
        "minor_event": {
            "id": "evt_wind",
            "description": "一陣微風吹過，帶來草嘅香味",
            "narrative_impact": "subtle",
        },
    }


# ============================================
# Test 1: StateChange.to_dict() uses schema format
# ============================================

class TestStateChangeUsesSchemaFormat:
    """``StateChange.to_dict()`` must produce {old, new, reason} sub-dicts."""

    def test_state_change_uses_schema_format(self):
        """
        A freshly built StateChange (via the calculator) must serialize to
        a dict whose stamina/health/morale fields are nested
        ``{old, new, reason}`` dicts — NOT integer delta fields.
        """
        calc = StateChangeCalculator()
        state = _make_character_state()
        result = calc.calculate(
            character_state=state,
            player_input={},
            scene_output={
                "state_changes": {
                    "stamina_delta": 1,
                    "health_delta": 0,
                    "morale_delta": -1,
                },
                "location": {},
            },
        )
        d = result.to_dict()

        # Top-level keys must match the schema's state_changes properties
        for axis in ("stamina", "health", "morale"):
            assert axis in d, f"missing top-level axis: {axis}"
            assert isinstance(d[axis], dict), f"{axis} must be a dict, got {type(d[axis])}"
            for sub_key in ("old", "new", "reason"):
                assert sub_key in d[axis], f"missing {axis}.{sub_key}"
                assert isinstance(d[axis][sub_key], str), (
                    f"{axis}.{sub_key} must be a string"
                )

        # The legacy _delta integer fields must NOT appear at the top level
        for bad_key in ("stamina_delta", "health_delta", "morale_delta"):
            assert bad_key not in d, f"legacy {bad_key} leaked into to_dict() output"

    def test_state_change_dataclass_has_reason_fields(self):
        """
        The StateChange dataclass must have explicit reason fields, separate
        from old/new. (This is the 'field layout' the schema requires.)
        """
        sc = StateChange(
            character_id="c1",
            stamina_old="fresh",
            stamina_new="slight_breath",
            health_old="healthy",
            health_new="healthy",
            morale_old="neutral",
            morale_new="neutral",
            stamina_reason="持續消耗",
            health_reason="無變化",
            morale_reason="無變化",
        )
        d = sc.to_dict()
        assert d["stamina"] == {
            "old": "fresh",
            "new": "slight_breath",
            "reason": "持續消耗",
        }
        assert d["health"]["reason"] == "無變化"
        assert d["morale"]["reason"] == "無變化"


# ============================================
# Test 2: Scene output validates against the JSON schema
# ============================================

class TestSceneOutputSchemaValidation:
    """A scene produced by the pipeline must validate against the schema."""

    def test_scene_output_validates_against_schema(self, scene_output_schema):
        """
        Build a representative scene_output dict (matching what SceneAgent
        produces) and validate it against the canonical JSON schema.
        """
        scene = _make_minimal_scene_output()
        # This will raise jsonschema.ValidationError on any schema mismatch
        jsonschema.validate(instance=scene, schema=scene_output_schema)

    def test_schema_loaded_from_canonical_path(self, scene_output_schema):
        """Sanity: the schema file is the right one (title = 'Scene Agent Output')."""
        assert scene_output_schema.get("title") == "Scene Agent Output"
        assert "state_changes" in scene_output_schema["properties"]

    def test_calculator_output_passes_schema(self, scene_output_schema):
        """
        The dict produced by ``StateChange.to_dict()`` (the canonical
        ``state_change_computed`` block) must validate as a sub-document
        against the schema's ``state_changes`` sub-schema.
        """
        calc = StateChangeCalculator()
        state = _make_character_state()
        result = calc.calculate(
            character_state=state,
            player_input={},
            scene_output={
                "state_changes": {
                    "stamina_delta": 1,
                    "health_delta": 1,
                    "morale_delta": -1,
                    "new_status_tags": ["輕微瘀傷"],
                    "new_memories": ["第一次冒險"],
                },
                "location": {},
            },
        )
        sc = result.to_dict()

        # Strip character_id (not in state_changes sub-schema) before validating
        sub = {k: v for k, v in sc.items() if k != "character_id"}
        jsonschema.validate(
            instance=sub,
            schema=scene_output_schema["properties"]["state_changes"],
        )

    def test_full_scene_with_calculator_output_validates(
        self, scene_output_schema
    ):
        """
        End-to-end: scene_output.state_changes = calculator.to_dict() should
        drop into the schema and validate.
        """
        calc = StateChangeCalculator()
        state = _make_character_state()
        result = calc.calculate(
            character_state=state,
            player_input={},
            scene_output={
                "state_changes": {"stamina_delta": 1},
                "location": {},
            },
        )
        scene = _make_minimal_scene_output()
        scene["state_changes"] = {
            "stamina": result.to_dict()["stamina"],
            "health":  result.to_dict()["health"],
            "morale":  result.to_dict()["morale"],
            "new_status_tags": result.to_dict()["new_status_tags"],
            "removed_status_tags": [],
            "items_consumed": [],
            "new_memories": [],
            "relationship_changes": [],
        }
        jsonschema.validate(instance=scene, schema=scene_output_schema)


# ============================================
# Test 3: Old delta format is rejected or auto-converted
# ============================================

class TestOldDeltaFormatHandled:
    """
    Legacy ``stamina_delta`` / ``health_delta`` / ``morale_delta`` style
    input must be **rejected** by the JSON schema (it's the source of
    truth) and **auto-converted** by the SceneAgent pipeline
    (``_normalize_state_changes``).
    """

    def test_old_delta_format_rejected_or_converted(self, scene_output_schema):
        """
        The schema's ``state_changes`` block is **permissive** by design —
        it doesn't reject the legacy ``stamina_delta`` integer fields
        (``additionalProperties`` is not set, so extras are tolerated).
        So the schema alone is not a sufficient guard.

        The protection comes from ``_normalize_state_changes`` in the
        SceneAgent pipeline, which must convert the legacy format into the
        schema format. This test asserts that contract: feeding legacy
        format in always yields a dict whose stamina/health/morale are
        proper ``{old, new, reason}`` sub-dicts and which validates against
        the schema's state_changes sub-schema.
        """
        legacy_raw = {
            "stamina_delta": 1,
            "health_delta": 0,
            "morale_delta": -1,
            "new_status_tags": ["wounded"],
        }

        # 1. _normalize_state_changes converts the legacy format
        normalized = _normalize_state_changes(
            legacy_raw,
            _make_character_state(),
        )

        # 2. Result validates against the schema's state_changes sub-schema
        jsonschema.validate(
            instance=normalized,
            schema=scene_output_schema["properties"]["state_changes"],
        )

        # 3. Sanity-check the conversion output
        for axis in ("stamina", "health", "morale"):
            assert isinstance(normalized[axis], dict)
            assert "old" in normalized[axis]
            assert "new" in normalized[axis]
            assert "reason" in normalized[axis]

        # 4. Critical: the legacy _delta integer fields must NOT appear
        #    in the normalized output (this is what the converter enforces).
        for bad_key in ("stamina_delta", "health_delta", "morale_delta"):
            assert bad_key not in normalized, (
                f"converter leaked legacy {bad_key} into normalized output"
            )

    def test_normalize_handles_all_three_legacy_axes(self):
        """The converter must understand stamina_delta, health_delta, morale_delta."""
        out = _normalize_state_changes(
            {
                "stamina_delta": 2,
                "health_delta": -1,
                "morale_delta": 0,
            },
            _make_character_state(),
        )
        for axis in ("stamina", "health", "morale"):
            assert isinstance(out[axis], dict)
            assert "reason" in out[axis]
        # delta=0 axes get the "no change" reason
        assert out["morale"]["reason"] == "無變化"

    def test_normalize_handles_malformed_input(self):
        """
        The converter is defensive: it must not raise on None, lists, or
        garbage input — it must always return a schema-valid dict.
        """
        for garbage in [None, [], "string", 42, {"stamina_delta": "not_an_int"}]:
            out = _normalize_state_changes(garbage, _make_character_state())
            for axis in ("stamina", "health", "morale"):
                assert isinstance(out[axis], dict)
                assert "reason" in out[axis]

    def test_normalize_preserves_already_valid_input(self):
        """
        If the LLM already produced schema-format input, the converter
        passes it through (with reason filled in if missing).
        """
        char = _make_character_state()
        out = _normalize_state_changes(
            {"stamina": {"old": "fresh", "new": "slight_breath"}},
            char,
        )
        # old/new preserved
        assert out["stamina"]["old"] == "fresh"
        assert out["stamina"]["new"] == "slight_breath"
        # reason auto-filled because it was missing
        assert out["stamina"]["reason"] == "狀態變化"


# ============================================
# Test 4: State machine reads the new format
# ============================================

class TestStateMachineReadsNewFormat:
    """``CharacterStateMachine.apply_round`` consumes ``stamina['new']`` etc."""

    def test_state_machine_reads_new_format(self, tmp_path, monkeypatch):
        """
        Build a scene_output with the schema-compliant state_change_computed
        block (nested {old, new, reason}), feed it through apply_round, and
        verify the character state was updated correctly.
        """
        # Redirect DB to a per-test temp file
        db_path = tmp_path / "schema_consistency.db"
        monkeypatch.setenv("SANDBOX_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

        from backend import db as db_mod, store as store_mod
        from backend.state_machine import CharacterStateMachine
        from backend import persistence

        try:
            # Build a scene_output in the new format
            scene = {
                "round": 1,
                "character_id": "char_sm_001",
                "narrative": "Test",
                "choices": [],
                "state_change_computed": {
                    "stamina": {"old": "fresh", "new": "slight_breath", "reason": "test"},
                    "health":  {"old": "healthy", "new": "healthy", "reason": "test"},
                    "morale":  {"old": "neutral", "new": "calm", "reason": "test"},
                    "new_status_tags": ["wounded"],
                    "removed_status_tags": [],
                    "items_consumed": [],
                    "new_memories": ["event A"],
                    "relationship_changes": [],
                    "blocked": [],
                },
            }
            init = {
                "character_id": "char_sm_001",
                "physical": {
                    "stamina_level": "fresh",
                    "health_status": "healthy",
                    "active_effects": [],
                },
                "mental": {"morale_level": "neutral"},
                "inventory": {"items": []},
                "memories": [],
                "relationships": {},
            }
            sm = CharacterStateMachine("char_sm_001", init)
            new_state = sm.apply_round({"character_id": "char_sm_001"}, scene)

            # The state machine must have read stamina['new'], health['new'],
            # morale['new'] from the new format and written them into the
            # canonical character_state fields.
            assert new_state["physical"]["stamina_level"] == "slight_breath"
            assert new_state["physical"]["health_status"] == "healthy"
            assert new_state["mental"]["morale_level"] == "calm"
            # Side-effects: tag added, memory added
            assert "wounded" in new_state["physical"]["active_effects"]
            assert "event A" in new_state["memories"]
        finally:
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(db_mod.dispose_engine())
                loop.close()
            except Exception:
                pass
            store_mod.store.characters.clear()
            store_mod.store.scenes.clear()
            store_mod.store.worlds.clear()

    def test_state_machine_ignores_delta_top_level_keys(self, tmp_path, monkeypatch):
        """
        If a scene_output mistakenly uses the legacy ``stamina_delta`` integer
        at the *top level of state_change_computed* (not inside stamina={...}),
        the state machine should NOT crash and should NOT change the stamina
        level — because there's no ``stamina['new']`` to read.
        """
        db_path = tmp_path / "schema_consistency_delta.db"
        monkeypatch.setenv("SANDBOX_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

        from backend import db as db_mod, store as store_mod
        from backend.state_machine import CharacterStateMachine

        scene = {
            "round": 1,
            "character_id": "char_sm_002",
            "narrative": "Test",
            "choices": [],
            "state_change_computed": {
                # Legacy shape — top-level integer
                "stamina_delta": 1,
                "health_delta": 0,
                "morale_delta": 0,
                "new_status_tags": [],
                "items_consumed": [],
                "new_memories": [],
                "relationship_changes": [],
            },
        }
        init = {
            "character_id": "char_sm_002",
            "physical": {
                "stamina_level": "fresh",
                "health_status": "healthy",
                "active_effects": [],
            },
            "mental": {"morale_level": "neutral"},
            "inventory": {"items": []},
            "memories": [],
            "relationships": {},
        }
        try:
            sm = CharacterStateMachine("char_sm_002", init)
            new_state = sm.apply_round({"character_id": "char_sm_002"}, scene)
            # Stamina should NOT have changed because the state machine only
            # reads stamina['new'], not stamina_delta.
            assert new_state["physical"]["stamina_level"] == "fresh"
        finally:
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(db_mod.dispose_engine())
                loop.close()
            except Exception:
                pass
            store_mod.store.characters.clear()
            store_mod.store.scenes.clear()
            store_mod.store.worlds.clear()


# ============================================
# Test 5: Reason field is always populated
# ============================================

class TestReasonFieldPopulated:
    """Every state change produced by the pipeline has a non-empty ``reason``."""

    def test_reason_field_populated(self):
        """
        For every (delta, environment, axis) combination the calculator
        handles, the produced StateChange must have a non-empty reason
        string on every axis.
        """
        calc = StateChangeCalculator()
        char = _make_character_state()
        for env in ("safe", "neutral", "unsafe"):
            for stamina_delta, health_delta, morale_delta in [
                (0, 0, 0),
                (1, 0, -1),
                (3, 0, 0),       # blocked clamp
                (0, -1, 2),      # mixed blocked
            ]:
                result = calc.calculate(
                    character_state=char,
                    player_input={},
                    scene_output={
                        "state_changes": {
                            "stamina_delta": stamina_delta,
                            "health_delta": health_delta,
                            "morale_delta": morale_delta,
                        },
                        "location": {"environment": env},
                    },
                )
                for axis in ("stamina_reason", "health_reason", "morale_reason"):
                    reason = getattr(result, axis)
                    assert reason, f"empty reason for {axis} (env={env}, deltas={(stamina_delta, health_delta, morale_delta)})"
                    assert isinstance(reason, str)

    def test_to_dict_reasons_match_attributes(self):
        """to_dict()['stamina']['reason'] == .stamina_reason, etc."""
        calc = StateChangeCalculator()
        result = calc.calculate(
            character_state=_make_character_state(),
            player_input={},
            scene_output={
                "state_changes": {"stamina_delta": 1},
                "location": {"environment": "neutral"},
            },
        )
        d = result.to_dict()
        assert d["stamina"]["reason"] == result.stamina_reason
        assert d["health"]["reason"] == result.health_reason
        assert d["morale"]["reason"] == result.morale_reason

    def test_reason_differs_for_safe_vs_unsafe(self):
        """
        The reason for a +1 stamina change in a safe environment should
        differ from one in an unsafe environment. (This is the whole point
        of environment-aware reason strings.)
        """
        calc = StateChangeCalculator()
        char = _make_character_state()
        safe = calc.calculate(
            character_state=char, player_input={},
            scene_output={
                "state_changes": {"stamina_delta": 1},
                "location": {"environment": "safe"},
            },
        )
        unsafe = calc.calculate(
            character_state=char, player_input={},
            scene_output={
                "state_changes": {"stamina_delta": 1},
                "location": {"environment": "unsafe"},
            },
        )
        assert safe.stamina_reason != unsafe.stamina_reason


# ============================================
# Bonus: System prompt should mention the schema format
# ============================================

class TestSystemPromptSchemaFormat:
    """
    The SceneAgent's system prompt should instruct the LLM to produce the
    schema-compliant ``{old, new, reason}`` shape, not the legacy
    ``_delta`` shape.
    """

    def test_prompt_does_not_mention_legacy_delta_keys(self):
        """The prompt must not ask the LLM for ``stamina_delta: int`` etc."""
        # The prompt is embedded inside an f-string template (double-braces
        # become single-braces in the rendered output). Check both forms.
        for marker in ("stamina_delta", "health_delta", "morale_delta"):
            assert marker not in SCENE_AGENT_SYSTEM_PROMPT, (
                f"system prompt still references legacy {marker}; LLM may "
                f"continue to emit the wrong format"
            )

    def test_prompt_mentions_schema_format(self):
        """The prompt should reference ``old`` and ``new`` and ``reason``."""
        for marker in ("old", "new", "reason"):
            assert marker in SCENE_AGENT_SYSTEM_PROMPT, (
                f"system prompt missing schema-format key: {marker}"
            )
