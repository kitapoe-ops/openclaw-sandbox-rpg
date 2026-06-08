"""
Prompt Inspector (2026-06-08)
============================

Read-only dev tool that exposes the LLM system prompt that PromptBuilder
would construct for a given character, without actually calling the LLM.

**Dev-only.** Gated by ``Settings.enable_prompt_inspector`` (default False).
Production deployments MUST keep this disabled.

**Read-only.** The endpoint does not write to the database, does not call
the LLM, and does not bypass the R1-14B audit. It is purely a
"what-would-the-LLM-see" preview.

Endpoints
---------
GET /api/prompt-inspector/preview?character_id=X
    Build the system prompt the LLM would see for the next action,
    using the current character state. Returns:
    - system_prompt: str  (the rendered template)
    - sections: dict       (the per-section breakdown, pre-format)
    - character_id: str
    - state_summary: dict  (compact character snapshot for context)
    - template_constant_keys: list[str]  (which {placeholders} exist)
    - flags: dict          (which systems are hidden, e.g. items/attitude)
    - generated_at: str    (ISO 8601 UTC)

GET /api/prompt-inspector/health
    Returns {enabled: bool, version: "2026-06-08"}. The frontend uses
    this to decide whether to mount the inspector panel.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..prompt_builder import PromptBuilder
from ..state_machine import SemanticState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prompt-inspector", tags=["prompt-inspector"])


def _is_enabled() -> bool:
    """Read the flag directly from the process environment.

    We avoid importing ``backend.config`` here because that module's
    ``Settings()`` instantiation eagerly reads ``.env`` and the existing
    comma-separated ``CORS_ORIGINS`` value fails pydantic-settings'
    JSON-list parser (pre-existing bug, out of scope). The env var
    approach gives the same gate without triggering that import.
    """
    return os.getenv("ENABLE_PROMPT_INSPECTOR", "false").lower() in ("1", "true", "yes", "on")


def _ensure_enabled() -> None:
    """Gate the whole module on the dev flag. 404 if disabled."""
    if not _is_enabled():
        raise HTTPException(
            status_code=404,
            detail="Prompt Inspector is disabled. Set ENABLE_PROMPT_INSPECTOR=true to enable.",
        )


@router.get("/health")
async def health() -> dict[str, Any]:
    """Public health endpoint. Always returns the flag state so the
    frontend can decide whether to render the inspector panel.
    No 404 here — the flag itself is the answer.
    """
    return {
        "enabled": _is_enabled(),
        "version": "2026-06-08",
        "scope": "read-only; no LLM call; no DB write; no audit bypass",
    }


@router.get("/preview")
async def preview_prompt(
    character_id: str = Query(..., min_length=1, description="Character to preview prompt for"),
) -> dict[str, Any]:
    """Build the system prompt for the given character without calling the LLM.

    Uses an in-memory placeholder SemanticState (no DB read) — this is a
    structural preview, not a faithful replay of the next action. The
    frontend can show this to verify template structure, section ordering,
    and which systems are hidden.
    """
    _ensure_enabled()

    # Use a placeholder state. The frontend UI shows this is structural.
    placeholder_state = SemanticState(
        character_id=character_id,
        tags=[],
        inventory={"items": []},
    )

    builder = PromptBuilder()
    # action_context is required by build() but unused in template
    sections: dict[str, str] = {
        "state_section": builder._format_state_section(placeholder_state),
        "equipment_section": builder._format_equipment_section(placeholder_state, world_db=None),
        "trope_section": builder._format_trope_section(placeholder_state),
        "action_context_section": builder._format_action_context({}),
    }

    system_prompt = (
        PromptBuilder.SYSTEM_PROMPT_TEMPLATE
        .replace("# 角色當前裝備與物理約束\n\n", "")
        .format(
            state_section=sections["state_section"],
            equipment_section=sections["equipment_section"],
            trope_section=sections["trope_section"],
            memory_section="(memory_section — populated async; not rendered in preview)",
            action_context_section=sections["action_context_section"],
        )
    )

    template_constant_keys = [
        name
        for _, name, _, _ in __import__("string").Formatter().parse(
            PromptBuilder.SYSTEM_PROMPT_TEMPLATE
        )
        if name
    ]

    return {
        "character_id": character_id,
        "system_prompt": system_prompt,
        "sections": sections,
        "template_constant_keys": template_constant_keys,
        "state_summary": {
            "character_id": placeholder_state.character_id,
            "tags": placeholder_state.tags,
            "inventory_items_count": len(placeholder_state.inventory.get("items", [])),
        },
        "flags": {
            "items_section_hidden": True,  # 2026-06-08: equipment always empty
            "attitude_section_in_prompt": False,  # never injected
            "r1_audit_bypassed": False,
        },
        "note": (
            "Structural preview only. Character state is a placeholder (no DB read). "
            "Memory section is not rendered (async). To see the actual prompt "
            "the LLM received for a past action, use a future audit-log endpoint."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
