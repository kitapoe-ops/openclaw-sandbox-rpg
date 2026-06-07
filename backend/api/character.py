"""
Character API Endpoints (v3.7 — demo + DB modes)
"""
from typing import Any

from fastapi import APIRouter, HTTPException

from ..demo_mode import is_demo_mode
from ..scenes_demo import get_demo_character

router = APIRouter()


@router.get("/{character_id}")
async def get_character(character_id: str) -> dict[str, Any]:
    """
    Get a character's current state.
    Demo mode: returns hard-coded character.
    Full mode: queries DB.
    """
    # Demo mode
    if is_demo_mode():
        demo = get_demo_character(character_id)
        if demo:
            return _demo_to_response(demo)
        # Default demo
        demo = get_demo_character("char demo_player")
        if demo:
            return _demo_to_response(demo)
        raise HTTPException(status_code=404, detail="Demo character not found")

    # Full mode
    try:
        from ..db import get_db_session
        from ..models import CharacterState

        async with get_db_session() as session:
            char = await session.get(CharacterState, character_id)
            if not char:
                # Phase L2-B: fail-loud. Don't fall back to demo data
                # in full mode. Return 404 explicitly.
                raise HTTPException(
                    status_code=404, detail=f"Character {character_id} not found"
                )

            return {
                "character_id": char.character_id,
                "name": char.name,
                "world_id": char.world_id,
                "current_scene_id": char.current_scene_id,
                "is_alive": char.is_alive,
                "is_npc_mode": char.is_npc_mode,
                "physical": char.semantic_profile.get("physical", {}),
                "mental": char.semantic_profile.get("mental", {}),
                "attitude": char.semantic_profile.get("attitude", {}),
                "inventory": char.semantic_profile.get("inventory", {}),
                "memories": char.semantic_profile.get("memories", []),
                "relationships": char.semantic_profile.get("relationships", {}),
            }
    except HTTPException:
        # Let 404 propagate as 404 (not caught by generic Exception)
        raise
    except Exception as e:
        # Real DB error — surface as 500, no demo fallback
        raise HTTPException(status_code=500, detail=f"DB error: {e}")


@router.post("/")
async def create_character(character_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new character."""
    return {"message": "TODO: Implement character creation", "received": character_data}


@router.put("/{character_id}")
async def update_character(character_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update a character (equipment change, etc.)."""
    return {
        "character_id": character_id,
        "message": "TODO: Implement character update",
        "updates": updates,
    }


def _demo_to_response(demo: dict[str, Any]) -> dict[str, Any]:
    """Convert demo data to API response format."""
    return {
        "character_id": demo["character_id"],
        "name": demo["name"],
        "world_id": demo["world_id"],
        "current_scene_id": demo["current_scene_id"],
        "is_alive": demo["is_alive"],
        "is_npc_mode": demo["is_npc_mode"],
        **demo["semantic_profile"],
        "mode": "demo",
    }
