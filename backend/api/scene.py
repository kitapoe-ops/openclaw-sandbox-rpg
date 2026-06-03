"""
Scene API endpoints - retrieve current scene.
"""
from fastapi import APIRouter
from typing import Dict, Any

router = APIRouter()


@router.get("/{character_id}")
async def get_current_scene(character_id: str) -> Dict[str, Any]:
    """
    Get the current scene for a character.

    Returns:
    - narrative (latest scene description)
    - 4 choices with attitude options
    - minor event
    - character state

    TODO: Implement scene retrieval.
    """
    return {
        "character_id": character_id,
        "message": "TODO: Implement scene retrieval",
    }


@router.get("/{character_id}/history")
async def get_scene_history(character_id: str, limit: int = 20) -> Dict[str, Any]:
    """
    Get last N scenes for the character.

    TODO: Implement history retrieval.
    """
    return {
        "character_id": character_id,
        "limit": limit,
        "message": "TODO: Implement history retrieval",
    }
