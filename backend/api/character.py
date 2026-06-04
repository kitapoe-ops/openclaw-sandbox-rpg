"""
Character API endpoints.

All endpoints go through the ``persistence.get_store()`` dispatcher so the
same code path can target either the in-process ``InMemoryStore`` (default,
mode="memory") or the SQLAlchemy-backed ``DBStore`` (mode="database").
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from datetime import datetime, timezone

from .. import persistence
UTC = timezone.utc


store = persistence.get_store()

router = APIRouter()

VALID_STAMINA = {"fresh", "slight_breath", "muscle_ache", "exhausted", "collapse"}
VALID_HEALTH = {"healthy", "wounded", "severely_wounded", "dying", "dead"}
VALID_MORALE = {"elated", "calm", "neutral", "anxious", "despair"}
VALID_ALERTNESS = {"sharp", "focused", "neutral", "distracted", "dazed"}

REQUIRED_FIELDS = (
    "character_id",
    "name",
    "world_id",
    "physical.stamina_level",
    "physical.health_status",
    "mental.morale_level",
)

ALLOWED_UPDATE_PATHS = {
    "name": "string",
    "current_location": "string",
    "physical.stamina_level": "stamina",
    "physical.health_status": "health",
    "mental.morale_level": "morale",
    "mental.alertness_level": "alertness",
    "attitude": "dict_str_str",
    "inventory": "dict",
}

def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace('+00:00', 'Z')

def _get_path(data: Dict[str, Any], dotted: str) -> Any:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node

_MISSING = object()

def _validate_required_fields(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for field in REQUIRED_FIELDS:
        if _get_path(data, field) is _MISSING:
            errors.append(f"Missing required field: {field}")
    return errors

def _validate_enum_values(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    stamina = _get_path(data, "physical.stamina_level")
    if stamina is not _MISSING and stamina not in VALID_STAMINA:
        errors.append(f"Invalid physical.stamina_level '{stamina}'. Must be one of: {sorted(VALID_STAMINA)}")
    health = _get_path(data, "physical.health_status")
    if health is not _MISSING and health not in VALID_HEALTH:
        errors.append(f"Invalid physical.health_status '{health}'. Must be one of: {sorted(VALID_HEALTH)}")
    morale = _get_path(data, "mental.morale_level")
    if morale is not _MISSING and morale not in VALID_MORALE:
        errors.append(f"Invalid mental.morale_level '{morale}'. Must be one of: {sorted(VALID_MORALE)}")
    return errors

def _apply_defaults(data: Dict[str, Any]) -> Dict[str, Any]:
    now = _now_iso()
    if not data.get("created_at"):
        data["created_at"] = now
    data["updated_at"] = now
    if "current_location" not in data or data["current_location"] is None:
        data["current_location"] = ""
    if "memories" not in data or data["memories"] is None:
        data["memories"] = []
    physical = data.setdefault("physical", {})
    if "active_effects" not in physical or physical["active_effects"] is None:
        physical["active_effects"] = []
    return data

def _validate_update_value(path: str, value: Any) -> str:
    expected = ALLOWED_UPDATE_PATHS[path]
    if expected == "string":
        if not isinstance(value, str):
            return f"Field '{path}' must be a string"
    elif expected == "stamina":
        if value not in VALID_STAMINA:
            return f"Invalid value for {path}: '{value}'. Must be one of: {sorted(VALID_STAMINA)}"
    elif expected == "health":
        if value not in VALID_HEALTH:
            return f"Invalid value for {path}: '{value}'. Must be one of: {sorted(VALID_HEALTH)}"
    elif expected == "morale":
        if value not in VALID_MORALE:
            return f"Invalid value for {path}: '{value}'. Must be one of: {sorted(VALID_MORALE)}"
    elif expected == "alertness":
        if value not in VALID_ALERTNESS:
            return f"Invalid value for {path}: '{value}'. Must be one of: {sorted(VALID_ALERTNESS)}"
    elif expected == "dict_str_str":
        if not isinstance(value, dict):
            return f"Field '{path}' must be a dict"
        for k, v in value.items():
            if not isinstance(k, str) or not isinstance(v, str):
                return f"Field '{path}' must map strings to strings"
    elif expected == "dict":
        if not isinstance(value, dict):
            return f"Field '{path}' must be a dict"
    return ""

def _set_path(target: Dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = target
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value

@router.post("/")
async def create_character(character_data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(character_data, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")
    missing_errors = _validate_required_fields(character_data)
    if missing_errors:
        raise HTTPException(status_code=400, detail={"errors": missing_errors})
    enum_errors = _validate_enum_values(character_data)
    if enum_errors:
        raise HTTPException(status_code=400, detail={"errors": enum_errors})
    character_id = character_data["character_id"]
    if await store.get_character(character_id) is not None:
        raise HTTPException(status_code=409, detail=f"Character '{character_id}' already exists")
    character = _apply_defaults(dict(character_data))
    await store.save_character(character)
    return character

@router.get("/")
async def list_characters() -> Dict[str, Any]:
    characters = await store.list_characters()
    return {"count": len(characters), "characters": characters}

@router.get("/{character_id}")
async def get_character(character_id: str) -> Dict[str, Any]:
    character = await store.get_character(character_id)
    if character is None:
        raise HTTPException(status_code=404, detail=f"Character '{character_id}' not found")
    character["updated_at"] = _now_iso()
    return character

@router.put("/{character_id}")
async def update_character(character_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(updates, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")
    existing = await store.get_character(character_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Character '{character_id}' not found")
    errors: List[str] = []
    for key in updates.keys():
        if key not in ALLOWED_UPDATE_PATHS:
            errors.append(f"Field '{key}' is not allowed for update. Allowed fields: {sorted(ALLOWED_UPDATE_PATHS.keys())}")
    for key, value in updates.items():
        if key in ALLOWED_UPDATE_PATHS:
            err = _validate_update_value(key, value)
            if err:
                errors.append(err)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})
    for key, value in updates.items():
        _set_path(existing, key, value)
    existing["updated_at"] = _now_iso()
    await store.save_character(existing)
    return existing
