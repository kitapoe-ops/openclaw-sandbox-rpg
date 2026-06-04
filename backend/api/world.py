"""
World API endpoints - world state and management.

All persistence calls go through the ``persistence.get_store()`` dispatcher.
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from datetime import datetime, timezone
from pathlib import Path

from .. import persistence
from ..world_lore_db import WorldLoreDB
UTC = timezone.utc


store = persistence.get_store()

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORLDS_DIR = _REPO_ROOT / "worlds"

def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace('+00:00', 'Z')

def _world_yaml_path(world_id: str) -> Path:
    return _WORLDS_DIR / f"{world_id}.yaml"

async def _ensure_world_loaded(world_id: str) -> Dict[str, Any]:
    existing = await store.get_world(world_id)
    if existing is not None:
        return existing
    yaml_path = _world_yaml_path(world_id)
    if not yaml_path.is_file():
        raise HTTPException(status_code=404, detail=f"World '{world_id}' not found (no YAML at {yaml_path})")
    try:
        import yaml
        with open(yaml_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load world YAML '{yaml_path}': {e}")
    lore = WorldLoreDB(world_id=world_id, world_config_path=yaml_path)
    lore.load_from_yaml(yaml_path)
    world_data: Dict[str, Any] = {
        "world_id": world_id,
        "world_meta": raw.get("world_meta", {}),
        "eternal": raw.get("eternal", {}),
        "world_parameters": raw.get("world_parameters", []),
        "attitude_dimensions": raw.get("attitude_dimensions", []),
        "npcs": raw.get("npcs", []),
        "items": raw.get("items", []),
        "locations": raw.get("locations", []),
        "quests": raw.get("quests", []),
        "starter_characters": raw.get("starter_characters", []),
        "physics_lock_rules": raw.get("physics_lock_rules", {}),
        "raw_yaml_path": str(yaml_path),
    }
    await store.load_world(world_id, world_data)
    return world_data

@router.get("/{world_id}/state")
async def get_world_state(world_id: str) -> Dict[str, Any]:
    world = await _ensure_world_loaded(world_id)
    return {
        "world_id": world_id,
        "loaded": True,
        "world_meta": world.get("world_meta", {}),
        "parameters": world.get("world_parameters", []),
        "locations_count": len(world.get("locations", [])),
        "npcs_count": len(world.get("npcs", [])),
        "items_count": len(world.get("items", [])),
    }

@router.get("/{world_id}/parameters")
async def get_world_parameters(world_id: str) -> Dict[str, Any]:
    world = await _ensure_world_loaded(world_id)
    raw_params = world.get("world_parameters", []) or []
    out: List[Dict[str, Any]] = []
    for p in raw_params:
        out.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "category": p.get("category"),
            "current_level": p.get("current_level", 0),
            "levels": p.get("levels", []),
            "description": p.get("description"),
            "fluctuation_limit": p.get("fluctuation_limit"),
        })
    return {"world_id": world_id, "parameters": out, "count": len(out)}

@router.post("/{world_id}/etl")
async def trigger_daily_etl(world_id: str) -> Dict[str, Any]:
    if not _world_yaml_path(world_id).is_file():
        raise HTTPException(status_code=404, detail=f"World '{world_id}' not found")
    world = await _ensure_world_loaded(world_id)
    now = _now_iso()
    etl_log = world.setdefault("etl_log", [])
    etl_log.append({"triggered_at": now, "status": "queued", "trigger": "manual"})
    world["last_etl_at"] = now
    world["last_etl_status"] = "queued"
    await store.load_world(world_id, world)
    return {"world_id": world_id, "etl_triggered_at": now, "status": "queued"}

@router.get("/{world_id}")
async def get_full_world(world_id: str) -> Dict[str, Any]:
    world = await _ensure_world_loaded(world_id)
    return {"world_id": world_id, "loaded": True, **world}
