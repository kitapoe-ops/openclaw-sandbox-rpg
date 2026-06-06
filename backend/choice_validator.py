"""
Player Choice Validator
========================
Validates player input against character state, world state, and game rules.

Reference: docs/SCHEMAS/player_input.schema.json
"""
from typing import Any

from jsonschema import ValidationError, validate

from .physics_lock import PhysicsLock


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

    TODO: Implement full validation.
    """

    def __init__(self, physics_lock: PhysicsLock = None):
        self.physics_lock = physics_lock or PhysicsLock()

    def validate(
        self,
        player_input: dict[str, Any],
        character_state: dict[str, Any],
        current_scene: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """
        Validate a player input. Returns (is_valid, list_of_errors).
        """
        errors = []

        # 1. Schema validation
        try:
            from ..docs.SCHEMAS.player_input_schema import PLAYER_INPUT_SCHEMA
            validate(instance=player_input, schema=PLAYER_INPUT_SCHEMA)
        except (ImportError, ValidationError) as e:
            errors.append(f"Schema validation failed: {e}")

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
            character_items = {i["item_id"]: i.get("quantity", 1) for i in character_state.get("inventory", {}).get("items", [])}
            for used in items_used:
                item_id = used["item_id"]
                qty = used["quantity"]
                if character_items.get(item_id, 0) < qty:
                    errors.append(f"Insufficient quantity of '{item_id}' (need {qty}, have {character_items.get(item_id, 0)})")

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
