"""
Action API endpoints - submit player choices.

All persistence calls go through the ``persistence.get_store()``
dispatcher, so the same code path can target either the in-process
``InMemoryStore`` (default) or the SQLAlchemy-backed ``DBStore``.
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any

from ..choice_validator import ChoiceValidator
from ..scene_agent import SceneAgent
from ..physics_lock import PhysicsLock
from ..semantic_gradient import StateChangeCalculator
from ..world_lore_db import WorldLoreDB
from .. import persistence

store = persistence.get_store()

router = APIRouter()

choice_validator = ChoiceValidator()
world_lore = WorldLoreDB("default")
state_calculator = StateChangeCalculator()
scene_agent = SceneAgent(
    world_lore=world_lore,
    physics_lock=PhysicsLock(),
    state_calculator=state_calculator,
)


@router.post("/submit")
async def submit_action(player_input: Dict[str, Any]) -> Dict[str, Any]:
    character_id = player_input.get("character_id")
    if not character_id:
        raise HTTPException(status_code=400, detail="character_id is required")
    character_state = await store.get_character(character_id)
    if not character_state:
        raise HTTPException(status_code=404, detail=f"Character '{character_id}' not found")
    current_scene = await store.get_latest_scene(character_id) or {"choices": []}
    is_valid, errors = choice_validator.validate(player_input, character_state, current_scene)
    if not is_valid:
        raise HTTPException(status_code=400, detail={"errors": errors})
    round_number = player_input.get("round", 1)
    world_state = await store.get_world(character_state.get("world_id", "default")) or {}
    scene_output = await scene_agent.generate_scene(
        character_state=character_state,
        player_input=player_input,
        world_state=world_state,
    )
    scene_output["round"] = round_number
    scene_output["character_id"] = character_id
    state_change_data = scene_output.get("state_change_computed", {})
    if state_change_data:
        new_physical = character_state.setdefault("physical", {})
        new_mental = character_state.setdefault("mental", {})
        if state_change_data.get("stamina", {}).get("new"):
            new_physical["stamina_level"] = state_change_data["stamina"]["new"]
        if state_change_data.get("health", {}).get("new"):
            new_physical["health_status"] = state_change_data["health"]["new"]
        if state_change_data.get("morale", {}).get("new"):
            new_mental["morale_level"] = state_change_data["morale"]["new"]
        for tag in state_change_data.get("new_status_tags", []):
            effects = new_physical.setdefault("active_effects", [])
            if tag not in effects and len(effects) < 8:
                effects.append(tag)
        for tag in state_change_data.get("removed_status_tags", []):
            effects = new_physical.get("active_effects", [])
            if tag in effects:
                effects.remove(tag)
        new_memories = state_change_data.get("new_memories", [])
        if new_memories:
            character_state.setdefault("memories", []).extend(new_memories)
    await store.save_scene(character_id, scene_output)
    await store.save_character(character_state)
    return {
        "scene": scene_output,
        "character_state": character_state,
        "round": round_number,
    }


@router.post("/auto")
async def auto_action(character_id: str) -> Dict[str, Any]:
    character_state = await store.get_character(character_id)
    if not character_state:
        raise HTTPException(status_code=404, detail=f"Character '{character_id}' not found")
    current_scene = await store.get_latest_scene(character_id) or {"choices": []}
    available = current_scene.get("choices", [])
    if not available:
        raise HTTPException(status_code=400, detail="No scene available for auto-action")
    auto_choice = next(
        (c for c in available if c.get("intent_category") == "delay"),
        next((c for c in available if c.get("intent_category") == "environment"), available[0]),
    )
    auto_input = {
        "round": (current_scene.get("round", 0) + 1),
        "character_id": character_id,
        "choice": {
            "option_id": auto_choice["id"],
            "attitude_selections": [
                {"dimension": "caution", "level": "balanced"}
            ],
        },
    }
    return await submit_action(auto_input)
