"""
Character State Machine
========================
Manages character state transitions and persistence.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import json

from .semantic_gradient import (
    SemanticGradient,
    StaminaLevel,
    HealthLevel,
    MoraleLevel,
)


class CharacterStateMachine:
    """
    Manages a single character's state.

    Implements the 9-step apply_round flow:
    1. Validate player_input against current state
    2. Apply scene_output.state_changes
    3. Update stamina/health/morale via SemanticGradient
    4. Add/remove status tags (max 8, mutex overwrite)
    5. Consume items
    6. Add memories
    7. Update relationships
    8. Mark updated_at
    9. Return new state
    """

    # Tag priorities — higher = more important, evicted last
    TAG_PRIORITIES: Dict[str, int] = {}

    def __init__(self, character_id: str, initial_state: Dict[str, Any]):
        self.character_id = character_id
        self.state = initial_state
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
        # Tag priorities side-channel: maps tag -> priority
        if "_tag_priorities" not in self.state:
            self.state["_tag_priorities"] = {}

    def get_state(self) -> Dict[str, Any]:
        """Return current state as dict."""
        return self.state

    def apply_round(self, player_input: Dict[str, Any], scene_output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply a round's state changes.
        """
        # Step 1: Basic validation
        if not isinstance(player_input, dict):
            raise ValueError("player_input must be a dict")
        if not isinstance(scene_output, dict):
            raise ValueError("scene_output must be a dict")

        # Step 2: Apply state_changes
        state_changes = scene_output.get("state_changes", {})

        # Step 3: Update stamina/health/morale
        physical = self.state.setdefault("physical", {})
        mental = self.state.setdefault("mental", {})

        if "stamina" in state_changes:
            sc = state_changes["stamina"]
            if isinstance(sc, dict) and "new" in sc:
                physical["stamina_level"] = sc["new"]
        if "health" in state_changes:
            sc = state_changes["health"]
            if isinstance(sc, dict) and "new" in sc:
                physical["health_status"] = sc["new"]
        if "morale" in state_changes:
            sc = state_changes["morale"]
            if isinstance(sc, dict) and "new" in sc:
                mental["morale_level"] = sc["new"]

        # Step 4: Status tags with mutex overwrite
        for tag in state_changes.get("new_status_tags", []):
            self.add_status_tag(tag, priority=5)
        for tag in state_changes.get("removed_status_tags", []):
            self.remove_status_tag(tag)

        # Step 5: Consume items
        items_consumed = state_changes.get("items_consumed", [])
        if items_consumed:
            inventory = self.state.setdefault("inventory", {})
            items = inventory.setdefault("items", [])
            for consumed in items_consumed:
                item_id = consumed.get("item_id")
                qty = consumed.get("quantity", 1)
                for item in items:
                    if item.get("item_id") == item_id:
                        item["quantity"] = max(0, item.get("quantity", 0) - qty)
                        if item["quantity"] == 0:
                            items.remove(item)
                        break

        # Step 6: Add memories
        new_memories = state_changes.get("new_memories", [])
        if new_memories:
            self.state.setdefault("memories", []).extend(new_memories)

        # Step 7: Update relationships
        rel_changes = state_changes.get("relationship_changes", [])
        if rel_changes:
            relationships = self.state.setdefault("relationships", {})
            for change in rel_changes:
                npc_id = change.get("npc_id")
                new_rel = change.get("new")
                if npc_id and new_rel:
                    relationships[npc_id] = new_rel

        # Step 8: Mark updated_at
        self.updated_at = datetime.now(timezone.utc)

        # Step 9: Return new state
        return self.state

    def add_status_tag(self, tag: str, priority: int = 5, ttl: Optional[int] = None) -> bool:
        """
        Add a status tag to the character.
        Max 8 tags. Mutex overwrite (lower priority tag gets evicted when full).
        """
        if "active_effects" not in self.state.get("physical", {}):
            self.state.setdefault("physical", {})["active_effects"] = []

        effects = self.state["physical"]["active_effects"]
        tag_priorities = self.state.setdefault("_tag_priorities", {})

        # Already present — just refresh priority
        if tag in effects:
            tag_priorities[tag] = priority
            self.updated_at = datetime.now(timezone.utc)
            return True

        # If at capacity, evict the lowest-priority tag
        if len(effects) >= 8:
            # Find the tag with the lowest priority
            lowest_tag = min(
                tag_priorities.keys() if tag_priorities else effects,
                key=lambda t: (tag_priorities.get(t, 5), effects.index(t)),
                default=None,
            )
            if lowest_tag and lowest_tag != tag:
                effects.remove(lowest_tag)
                tag_priorities.pop(lowest_tag, None)
            else:
                # All 8 have equal priority and we can't evict; skip add
                return False

        effects.append(tag)
        tag_priorities[tag] = priority
        self.updated_at = datetime.now(timezone.utc)
        return True

    def remove_status_tag(self, tag: str) -> bool:
        """Remove a status tag."""
        effects = self.state.get("physical", {}).get("active_effects", [])
        tag_priorities = self.state.get("_tag_priorities", {})
        if tag in effects:
            effects.remove(tag)
            tag_priorities.pop(tag, None)
            self.updated_at = datetime.now(timezone.utc)
            return True
        return False
