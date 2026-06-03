"""
Scene API Endpoints (v3.6 — real DB queries)
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from typing import Dict, Any

from ..db import get_db_session
from ..models import CharacterState, Scene
from ..scenes_demo import DEMO_SCENE, DEMO_STARTER, get_demo_scene

router = APIRouter()


@router.get("/{character_id}")
async def get_current_scene(character_id: str) -> Dict[str, Any]:
    """
    Get the current scene for a character.
    Loads from DB character_states.current_scene_id, then loads scene content.
    Falls back to demo data if scene not in DB.
    """
    async with get_db_session() as session:
        # 1. Get character (to find current_scene_id)
        char = await session.get(CharacterState, character_id)
        if not char:
            # Fall back to demo
            demo = get_demo_scene("loc_phandalin_town")
            if demo:
                return _format_scene_response(character_id, demo)
            raise HTTPException(status_code=404, detail=f"Character {character_id} not found")

        scene_id = char.current_scene_id

        # 2. Get scene content from DB
        scene = await session.get(Scene, scene_id)
        if not scene:
            # Fall back to demo
            demo = get_demo_scene(scene_id)
            if demo:
                return _format_scene_response(character_id, demo)
            raise HTTPException(status_code=404, detail=f"Scene {scene_id} not found")

        # 3. Build response
        return {
            "round": 1,  # TODO: track current round
            "character_id": character_id,
            "scene_id": scene.id,
            "narrative": scene.description,
            "choices": DEMO_SCENE["choices"],  # TODO: load from scene.choices JSON
            "state_changes": {},
            "minor_event": None,
        }


@router.get("/{character_id}/history")
async def get_scene_history(character_id: str, limit: int = 20) -> Dict[str, Any]:
    """Get last N scenes for the character (narrative history)."""
    # TODO: Implement when action_history.narrative_output is populated
    return {
        "character_id": character_id,
        "limit": limit,
        "history": [],
    }


def _format_scene_response(character_id: str, scene: Dict[str, Any]) -> Dict[str, Any]:
    """Format scene data into API response."""
    return {
        "round": 1,
        "character_id": character_id,
        "scene_id": scene["scene_id"],
        "narrative": scene["scene_narrative"],
        "choices": scene["choices"],
        "state_changes": {},
        "minor_event": scene.get("minor_event"),
    }
