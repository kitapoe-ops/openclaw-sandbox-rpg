"""
Player Choice Validator
========================
Validates player input against character state, world state, and game rules.

Reference: docs/SCHEMAS/player_input.schema.json
"""
from typing import Dict, Any, Tuple, List, Optional
from pathlib import Path
import json
import logging

from .physics_lock import PhysicsLock

logger = logging.getLogger(__name__)


def _load_schema(schema_filename: str) -> Optional[Dict[str, Any]]:
    """
    Load a JSON schema from docs/SCHEMAS/ relative to repo root.
    Returns None if file not found.
    """
    # backend/choice_validator.py → repo root is parent of parent
    repo_root = Path(__file__).resolve().parent.parent
    schema_path = repo_root / "docs" / "SCHEMAS" / schema_filename
    if not schema_path.exists():
        logger.warning(f"Schema file not found: {schema_path}")
        return None
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load schema {schema_path}: {e}")
        return None


class ChoiceValidator:
    """
    Validates a player's choice submission.

    Validation layers:
    1. Schema validation (player_input.schema.json)
    2. Choice availability (is option_id in current 4 choices?)
    3. Attitude validity (are dimension/level combinations allowed?)
    4. Equipment validity (does player own the equipment?)
    5. Item usage validity (does player have enough items?)
    6. Physics lock (can character physically do this?)
    """

    def __init__(self, physics_lock: Optional[PhysicsLock] = None):
        self.physics_lock = physics_lock or PhysicsLock()
        # Try to load schema; if jsonschema is installed, use it
        self._schema = _load_schema("player_input.schema.json")
        try:
            from jsonschema import validate, ValidationError  # noqa
            self._validator_available = True
        except ImportError:
            self._validator_available = False

    def validate(
        self,
        player_input: Dict[str, Any],
        character_state: Dict[str, Any],
        current_scene: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        """
        Validate a player input. Returns (is_valid, list_of_errors).
        """
        errors = []

        # 1. Schema validation (only if jsonschema is available)
        if self._validator_available and self._schema:
            try:
                from jsonschema import validate, ValidationError
                validate(instance=player_input, schema=self._schema)
            except ValidationError as e:
                errors.append(f"Schema validation failed: {e.message}")
            except Exception as e:
                errors.append(f"Schema validation error: {e}")

        # 2. Choice availability
        available_choices = current_scene.get("choices", [])
        option_id = player_input.get("choice", {}).get("option_id")
        if option_id and not any(c["id"] == option_id for c in available_choices):
            errors.append(f"Option '{option_id}' is not available in current scene")

        # 3. Attitude validity
        attitude_selections = player_input.get("choice", {}).get("attitude_selections", [])
        if not (1 <= len(attitude_selections) <= 2):
            errors.append("Must select 1-2 attitude dimensions")

        # 4. Equipment validity
        equipment_change = player_input.get("equipment_change", {})
        if equipment_change:
            character_equipment = character_state.get("inventory", {}).get("items", [])
            for slot, item_id in equipment_change.items():
                if not any(i.get("item_id") == item_id for i in character_equipment):
                    errors.append(f"Character does not own equipment '{item_id}' for slot '{slot}'")

        # 5. Item usage validity
        items_used = player_input.get("items_used", [])
        if items_used:
            character_items = {
                i["item_id"]: i.get("quantity", 1)
                for i in character_state.get("inventory", {}).get("items", [])
            }
            for used in items_used:
                item_id = used["item_id"]
                qty = used["quantity"]
                if character_items.get(item_id, 0) < qty:
                    errors.append(
                        f"Insufficient quantity of '{item_id}' "
                        f"(need {qty}, have {character_items.get(item_id, 0)})"
                    )

        # 6. Physics lock
        if available_choices and option_id:
            selected_choice = next((c for c in available_choices if c["id"] == option_id), None)
            if selected_choice:
                is_valid, reason = self.physics_lock.validate_choice(
                    selected_choice["text"],
                    character_state,
                )
                if not is_valid:
                    # NOTE: We don't reject — we preserve intent and let LLM improvise
                    # Just flag for downstream
                    player_input["_physics_lock_warning"] = reason

        return len(errors) == 0, errors

