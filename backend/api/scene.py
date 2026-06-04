"""
Scene API endpoints - retrieve current scene and history.

All persistence calls go through the ``persistence.get_store()`` dispatcher.
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from datetime import datetime, timezone

from .. import persistence
UTC = timezone.utc


store = persistence.get_store()

router = APIRouter()

def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace('+00:00', 'Z')

@router.get("/{character_id}")
async def get_current_scene(character_id: str) -> Dict[str, Any]:
    if await store.get_character(character_id) is None:
        raise HTTPException(status_code=404, detail=f"Character '{character_id}' not found")
    scene = await store.get_latest_scene(character_id)
    if scene is None:
        raise HTTPException(
            status_code=404,
            detail=(f"No scene found for character '{character_id}'. "
                    "POST /api/scene/{character_id}/seed to create one."),
        )
    return scene

@router.get("/{character_id}/history")
async def get_scene_history(character_id: str, limit: int = 20) -> Dict[str, Any]:
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    if limit > 100:
        limit = 100
    if await store.get_character(character_id) is None:
        raise HTTPException(status_code=404, detail=f"Character '{character_id}' not found")
    scenes = await store.get_scene_history(character_id, limit=limit)
    return {"character_id": character_id, "scenes": scenes, "count": len(scenes)}

@router.post("/{character_id}/seed")
async def seed_scene(character_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if await store.get_character(character_id) is None:
        raise HTTPException(status_code=404, detail=f"Character '{character_id}' not found")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")
    if "round" not in payload:
        raise HTTPException(status_code=400, detail="Missing required field: round")
    if "narrative" not in payload:
        raise HTTPException(status_code=400, detail="Missing required field: narrative")
    if "choices" not in payload:
        raise HTTPException(status_code=400, detail="Missing required field: choices")
    if not isinstance(payload["round"], int):
        raise HTTPException(status_code=400, detail="Field 'round' must be an int")
    if not isinstance(payload["narrative"], str):
        raise HTTPException(status_code=400, detail="Field 'narrative' must be a string")
    if not isinstance(payload["choices"], list):
        raise HTTPException(status_code=400, detail="Field 'choices' must be a list")
    scene: Dict[str, Any] = {
        "round": payload["round"],
        "character_id": character_id,
        "narrative": payload["narrative"],
        "choices": payload["choices"],
        "state_changes": payload.get("state_changes", {}),
        "minor_event": payload.get("minor_event"),
        "state_change_computed": payload.get("state_change_computed", {}),
        "created_at": _now_iso(),
    }
    if "location_id" in payload:
        scene["location_id"] = payload["location_id"]
    await store.save_scene(character_id, scene)
    return scene
