"""
Action API Endpoints (v3.6)
"""
from typing import Any

from fastapi import APIRouter

from ..ws import registry

router = APIRouter()


@router.post("/submit")
async def submit_action(player_input: dict[str, Any]) -> dict[str, Any]:
    """
    Submit a player's action (HTTP fallback for non-WebSocket clients).
    In production, prefer WebSocket; this is for debugging.
    """
    # Just echo back — actual processing happens via WS
    return {
        "message": "Use WebSocket /ws/game/{character_id} for real-time action submission",
        "received": player_input,
        "registry_stats": registry.stats(),
    }


@router.post("/auto")
async def auto_action(character_id: str) -> dict[str, Any]:
    """Trigger NPC auto-behavior when player doesn't submit in 15 min."""
    return {
        "character_id": character_id,
        "message": "TODO: Implement NPC auto-behavior (Sub Agent generates default action)",
    }
