"""
Character API Endpoints (v3.6 — real DB queries)
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any

from ..db import get_db_session
from ..models import CharacterState
from ..scenes_demo import get_demo_character

router = APIRouter()


@router.get("/{character_id}")
async def get_character(character_id: str) -> Dict[str, Any]:
    """
    Get a character's current state.
    Returns character_states.semantic_profile from DB.
    """
    async with get_db_session() as session:
        char = await session.get(CharacterState, character_id)
        if not char:
            # Fallback to demo
            demo = get_demo_character(character_id)
            if demo:
                return _demo_to_response(demo)
            raise HTTPException(status_code=404, detail=f"Character {character_id} not found")

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


@router.post("/")
async def create_character(character_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new character."""
    # TODO: Implement with proper auth + world validation
    return {"message": "TODO: Implement character creation", "received": character_data}


@router.put("/{character_id}")
async def update_character(character_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update a character (equipment change, etc.)."""
    return {
        "character_id": character_id,
        "message": "TODO: Implement character update",
        "updates": updates,
    }


def _demo_to_response(demo: Dict[str, Any]) -> Dict[str, Any]:
    """Convert demo data to API response format."""
    return {
        "character_id": demo["character_id"],
        "name": demo["name"],
        "world_id": demo["world_id"],
        "current_scene_id": demo["current_scene_id"],
        "is_alive": demo["is_alive"],
        "is_npc_mode": demo["is_npc_mode"],
        **demo["semantic_profile"],
    }
