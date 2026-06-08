"""
Phase L2-I/Phase B: Shared world state + cross-player broadcast tests.

Verifies:
  1. Two fake characters can register in the same scene and both
     receive cross-player broadcasts (excluding the actor).
  2. Characters in different scenes do NOT receive each other's
     broadcasts.
  3. The scene_npc_states table exists and is queryable.
  4. The PromptBuilder._format_npc_state_section produces
     well-formatted output.
  5. The `other_player_action` message shape includes the
     expected fields.
"""
import asyncio
import pytest

from backend.ws.connection_manager import registry
from backend.prompt_builder import PromptBuilder
from backend.models import SceneNpcState
from sqlalchemy import select


# ============================================
# 1. Cross-player broadcast works
# ============================================


class FakeWS:
    """Minimal WebSocket stand-in that records sent messages."""

    def __init__(self) -> None:
        self.received: list[dict] = []

    async def send_json(self, msg: dict) -> None:
        self.received.append(msg)


@pytest.mark.asyncio
async def test_cross_player_broadcast_same_scene():
    registry_local = registry  # Use the module-level singleton
    # Reset state for a clean test
    await registry_local.unregister("ph_b_alice", "c1")
    await registry_local.unregister("ph_b_bob", "c2")
    await registry_local.unregister("ph_b_carol", "c3")

    alice_ws = FakeWS()
    bob_ws = FakeWS()
    carol_ws = FakeWS()

    await registry_local.register("ph_b_alice", "c1", alice_ws, scene_id="scene_x")
    await registry_local.register("ph_b_bob", "c2", bob_ws, scene_id="scene_x")
    await registry_local.register("ph_b_carol", "c3", carol_ws, scene_id="scene_y")

    sent = await registry_local.broadcast_to_scene(
        "scene_x",
        {"type": "other_player_action", "actor": "ph_b_alice", "narrative": "alice acts"},
        exclude_character_id="ph_b_alice",
    )

    assert sent == 1
    assert len(alice_ws.received) == 0  # excluded
    assert len(bob_ws.received) == 1  # same scene
    assert bob_ws.received[0]["actor"] == "ph_b_alice"
    assert len(carol_ws.received) == 0  # different scene

    # Cleanup
    await registry_local.unregister("ph_b_alice", "c1")
    await registry_local.unregister("ph_b_bob", "c2")
    await registry_local.unregister("ph_b_carol", "c3")


@pytest.mark.asyncio
async def test_broadcast_to_scene_with_no_audience():
    sent = await registry.broadcast_to_scene("nonexistent_scene", {"x": 1})
    assert sent == 0


@pytest.mark.asyncio
async def test_set_scene_updates_mapping():
    """After set_scene, the character is in the new scene."""
    await registry.unregister("ph_b_dan", "c4")
    dan_ws = FakeWS()
    await registry.register("ph_b_dan", "c4", dan_ws, scene_id="scene_a")
    assert await registry.characters_in_scene("scene_a") == ["ph_b_dan"]

    await registry.set_scene("ph_b_dan", "scene_b")
    assert await registry.characters_in_scene("scene_a") == []
    assert await registry.characters_in_scene("scene_b") == ["ph_b_dan"]
    await registry.unregister("ph_b_dan", "c4")


# ============================================
# 2. scene_npc_states table is reachable
# ============================================


@pytest.mark.asyncio
async def test_scene_npc_state_table_exists():
    """Verify the model can be queried (table exists in DB)."""
    from backend.db import get_db_session
    from sqlalchemy import text

    async with get_db_session() as session:
        result = await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='scene_npc_states'"
            )
        )
        rows = [r[0] for r in result]
        assert "scene_npc_states" in rows, f"scene_npc_states table not found; got {rows}"


# ============================================================
# 3. PromptBuilder NPC state section
# ============================================================


def test_format_npc_state_section_empty():
    pb = PromptBuilder()
    out = pb._format_npc_state_section([])
    assert "未記錄" in out or "未記錄" in out


def test_format_npc_state_section_sorted_dead_first():
    pb = PromptBuilder()
    npcs = [
        {"npc_id": "npc_halia", "status": "hostile", "detail": "wounded"},
        {"npc_id": "npc_redbrand", "status": "dead", "detail": "slain"},
        {"npc_id": "npc_sister", "status": "friendly", "detail": ""},
    ]
    out = pb._format_npc_state_section(npcs)
    # dead should appear first
    dead_idx = out.find("npc_redbrand")
    hostile_idx = out.find("npc_halia")
    friendly_idx = out.find("npc_sister")
    assert dead_idx < hostile_idx < friendly_idx


def test_format_npc_state_section_includes_detail():
    pb = PromptBuilder()
    npcs = [
        {"npc_id": "npc_halia", "status": "hostile", "detail": "wounded in combat"},
    ]
    out = pb._format_npc_state_section(npcs)
    assert "npc_halia" in out
    assert "hostile" in out
    assert "wounded in combat" in out


# ============================================================
# 4. WS message type added
# ============================================================


def test_other_player_action_message_type_exists():
    """Phase L2-I/Phase B: the WS protocol includes other_player_action."""
    # Read the TS file directly to check (avoids needing the TS bundle)
    ws_ts = open(
        r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\frontend\src\services\websocket.ts",
        encoding="utf-8",
    ).read()
    assert "other_player_action" in ws_ts, (
        "frontend/src/services/websocket.ts should include the " "other_player_action message type"
    )
