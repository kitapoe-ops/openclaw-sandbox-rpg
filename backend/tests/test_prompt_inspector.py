"""Tests for the Prompt Inspector dev-only endpoint (2026-06-08).

These tests use the FastAPI TestClient and the dedicated env var
ENABLE_PROMPT_INSPECTOR, NOT backend.config, because the existing
config.py has a pre-existing .env parsing bug (CORS_ORIGINS format)
that is out of scope for this commit.
"""
import os
import pytest
from fastapi.testclient import TestClient


def _build_isolated_app():
    """Build a FastAPI app that mounts ONLY the prompt inspector router
    and the demo mode safety guard. Avoids the main app's circular imports
    and the pre-existing CORS_ORIGINS parse bug.
    """
    from fastapi import FastAPI
    from backend.api.prompt_inspector import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestPromptInspectorHealth:
    """The /health endpoint is always mounted; it returns the flag state."""

    def test_health_returns_flag_state(self):
        # Force flag off for this test
        os.environ["ENABLE_PROMPT_INSPECTOR"] = "false"
        client = TestClient(_build_isolated_app())
        resp = client.get("/api/prompt-inspector/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert data["enabled"] is False
        assert data["version"] == "2026-06-08"
        assert "read-only" in data["scope"]

    def test_health_reflects_flag_true(self):
        os.environ["ENABLE_PROMPT_INSPECTOR"] = "true"
        client = TestClient(_build_isolated_app())
        resp = client.get("/api/prompt-inspector/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True


class TestPromptInspectorPreviewGate:
    """/preview returns 404 when the flag is off, regardless of character_id."""

    def test_preview_returns_404_when_disabled(self):
        os.environ["ENABLE_PROMPT_INSPECTOR"] = "false"
        client = TestClient(_build_isolated_app())
        resp = client.get("/api/prompt-inspector/preview?character_id=alice")
        assert resp.status_code == 404
        assert "disabled" in resp.json()["detail"].lower()


class TestPromptInspectorPreviewContent:
    """/preview returns structural prompt content when the flag is on."""

    @pytest.fixture(autouse=True)
    def _enable_flag(self):
        os.environ["ENABLE_PROMPT_INSPECTOR"] = "true"
        yield
        os.environ["ENABLE_PROMPT_INSPECTOR"] = "false"

    def test_preview_returns_full_response_shape(self):
        client = TestClient(_build_isolated_app())
        resp = client.get("/api/prompt-inspector/preview?character_id=alice")
        assert resp.status_code == 200
        data = resp.json()

        # Top-level keys
        assert data["character_id"] == "alice"
        assert isinstance(data["system_prompt"], str)
        assert len(data["system_prompt"]) > 0
        assert "sections" in data
        assert "template_constant_keys" in data
        assert "state_summary" in data
        assert "flags" in data
        assert "generated_at" in data

    def test_preview_sections_match_template(self):
        client = TestClient(_build_isolated_app())
        resp = client.get("/api/prompt-inspector/preview?character_id=bob")
        sections = resp.json()["sections"]
        # Items section is hidden → empty string
        assert sections["equipment_section"] == ""
        # Other sections are present
        assert "state_section" in sections
        assert "trope_section" in sections
        assert "action_context_section" in sections

    def test_preview_system_prompt_excludes_hidden_header(self):
        """The equipment section header must be stripped from the rendered prompt."""
        client = TestClient(_build_isolated_app())
        resp = client.get("/api/prompt-inspector/preview?character_id=carol")
        prompt = resp.json()["system_prompt"]
        # Hidden 2026-06-08: the equipment header line is stripped
        assert "# 角色當前裝備與物理約束" not in prompt
        # But the other headers must remain
        assert "# 角色當前狀態" in prompt
        assert "# 故事套路約束" in prompt
        assert "# 角色記憶摘要" in prompt
        assert "# 動作上下文" in prompt
        assert "# 輸出格式要求" in prompt
        assert "# 重要規則" in prompt

    def test_preview_flags_state(self):
        client = TestClient(_build_isolated_app())
        resp = client.get("/api/prompt-inspector/preview?character_id=dave")
        flags = resp.json()["flags"]
        assert flags["items_section_hidden"] is True
        assert flags["attitude_section_in_prompt"] is False
        # Critical: the inspector never bypasses R1 audit
        assert flags["r1_audit_bypassed"] is False
        # 2026-06-08: F3 state contract + 5-module user prompt
        assert flags.get("f3_state_contract_preserved") is True
        assert flags.get("user_prompt_5_module") is True

    def test_preview_user_prompt_section(self):
        """2026-06-08: /preview also returns the 5-module user prompt."""
        client = TestClient(_build_isolated_app())
        resp = client.get("/api/prompt-inspector/preview?character_id=alice")
        data = resp.json()
        assert "user_prompt" in data
        up = data["user_prompt"]
        assert "rendered" in up
        assert "sections" in up
        assert "template_constant_keys" in up
        assert "allowed_choice_directions" in up
        assert up["module_count"] == 5
        # The rendered user prompt must contain the 5 module headers
        for i in range(1, 6):
            assert f"### [模塊 {i}：" in up["rendered"]
        # The section breakdown must include the expected keys
        for key in (
            "character_id", "health_status", "inventory_with_physical_tags",
            "scene_npc_states", "active_escalation_threads",
            "other_player_footprints", "verb", "target", "args_str",
            "current_trope_directive",
        ):
            assert key in up["sections"]

    def test_preview_template_constants_listed(self):
        client = TestClient(_build_isolated_app())
        resp = client.get("/api/prompt-inspector/preview?character_id=eve")
        keys = resp.json()["template_constant_keys"]
        assert "state_section" in keys
        assert "equipment_section" in keys
        assert "trope_section" in keys
        assert "memory_section" in keys
        assert "action_context_section" in keys

    def test_preview_placeholder_state_for_structural_view(self):
        """The endpoint uses a placeholder state; this is structural."""
        client = TestClient(_build_isolated_app())
        resp = client.get("/api/prompt-inspector/preview?character_id=alice")
        summary = resp.json()["state_summary"]
        assert summary["character_id"] == "alice"
        assert summary["tags"] == []
        assert summary["inventory_items_count"] == 0
