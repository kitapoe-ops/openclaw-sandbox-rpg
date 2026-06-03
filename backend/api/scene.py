"""
Scene API Endpoints (v3.7 — demo + DB modes)
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any

from ..scenes_demo import DEMO_SCENE, get_demo_scene
from ..demo_mode import is_demo_mode

router = APIRouter()


@router.get("/{character_id}")
async def get_current_scene(character_id: str) -> Dict[str, Any]:
    """
    Get the current scene for a character.
    Demo mode: returns hard-coded scene based on character.
    Full mode: queries DB for character.current_scene_id, then scene.
    """
    # Demo mode: just return demo scene
    if is_demo_mode():
        demo = get_demo_scene("loc_phandalin_town")
        if demo:
            return {
                "round": 1,
                "character_id": character_id,
                "scene_id": demo["scene_id"],
                "narrative": demo["scene_narrative"],
                "choices": demo["choices"],
                "state_changes": {},
                "minor_event": demo.get("minor_event"),
                "mode": "demo",
            }
        raise HTTPException(status_code=404, detail="Demo scene not found")

    # Full mode: query DB
    try:
        from ..db import get_db_session
        from ..models import CharacterState, Scene

        async with get_db_session() as session:
            char = await session.get(CharacterState, character_id)
            if not char:
                # Fallback to demo
                demo = get_demo_scene("loc_phandalin_town")
                if demo:
                    return _format_demo_response(character_id, demo)
                raise HTTPException(status_code=404, detail=f"Character {character_id} not found")

            scene = await session.get(Scene, char.current_scene_id)
            if not scene:
                raise HTTPException(status_code=404, detail=f"Scene {char.current_scene_id} not found")

            return {
                "round": 1,
                "character_id": character_id,
                "scene_id": scene.id,
                "narrative": scene.description,
                "choices": DEMO_SCENE["choices"],  # TODO: persist scene choices
                "state_changes": {},
                "minor_event": None,
            }
    except Exception as e:
        # DB error — fall back to demo
        demo = get_demo_scene("loc_phandalin_town")
        if demo:
            return _format_demo_response(character_id, demo)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_id}/history")
async def get_scene_history(character_id: str, limit: int = 20) -> Dict[str, Any]:
    """Get last N scenes for the character."""
    return {
        "character_id": character_id,
        "limit": limit,
        "history": [],
        "mode": "demo" if is_demo_mode() else "full",
    }


def _format_demo_response(character_id: str, scene: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "round": 1,
        "character_id": character_id,
        "scene_id": scene["scene_id"],
        "narrative": scene["scene_narrative"],
        "choices": scene["choices"],
        "state_changes": {},
        "minor_event": scene.get("minor_event"),
        "mode": "demo",
    }
