"""
Character State Machine
========================
Manages character state transitions and persistence.

The state machine applies a round's worth of changes computed by
``StateChangeCalculator`` to the in-memory ``self.state`` dict, then asks
``persistence`` to write the new state. It also maintains a side-channel
``self.tag_priorities`` dict for mutex-aware status-tag eviction (lowest
priority is dropped when the active_effects list hits its cap).
"""
from __future__ import annotations

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import logging

from .semantic_gradient import (
    SemanticGradient,
    StaminaLevel,
    HealthLevel,
    MoraleLevel,
)
from . import persistence
UTC = timezone.utc


logger = logging.getLogger(__name__)

# ============================================
# Constants
# ============================================

# Default maximum number of active effects (status tags) per character.
# Can be overridden by world_parameter_config (passed via state). 8 matches the
# schema's maxItems=8 and the config default in config.py.
MAX_TAGS_DEFAULT = 8

# Default priority assigned to a new status tag (range 1-10). Higher = more
# important; will displace lower-priority tags when the list overflows.
DEFAULT_TAG_PRIORITY = 5

# Allowed relationship levels (mirrors character_state.schema.json).
RELATIONSHIP_LEVELS = {
    "hostile", "wary", "neutral", "friendly", "trusted", "devoted",
}

# ============================================
# State Machine
# ============================================

class CharacterStateMachine:
    """
    Manages a single character's state.

    The state machine owns a dict (``self.state``) shaped like
    ``character_state.schema.json``. It does not know about HTTP, LLM, or
    schema validation; those concerns live elsewhere.
    """

    def __init__(self, character_id: str, initial_state: Dict[str, Any]):
        self.character_id = character_id
        # Defensive copy so we never mutate the caller's dict.
        self.state: Dict[str, Any] = {k: v for k, v in (initial_state or {}).items()}
        self.state.setdefault("character_id", character_id)
        self.state.setdefault("physical", {})
        self.state.setdefault("mental", {})

        # Side-channel: parallel dict tracking each active_effect's priority.
        # Stored at the top level (not inside ``state``) so it never leaks
        # into JSON serialization or schema validation.
        self.tag_priorities: Dict[str, int] = {}

        # Round counter ??incremented on every successful apply_round.
        self.round: int = int(self.state.get("round", 0) or 0)

        self.created_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)

    # --------------------------------------------------------------------
    # Public helpers
    # --------------------------------------------------------------------

    def get_state(self) -> Dict[str, Any]:
        """Return current state as dict (shallow copy)."""
        return dict(self.state)

    def get_max_tags(self) -> int:
        """Read max_tags from state.world_parameter_config, else default."""
        wp = self.state.get("world_parameter_config") or {}
        try:
            return int(wp.get("max_tags_per_character", MAX_TAGS_DEFAULT))
        except (TypeError, ValueError):
            return MAX_TAGS_DEFAULT

    # --------------------------------------------------------------------
    # apply_round ??the main round transition
    # --------------------------------------------------------------------

    def apply_round(
        self,
        player_input: Dict[str, Any],
        scene_output: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Apply a round's state changes.

        Steps:
        1. Validate player_input against current state
        2. Apply scene_output.state_change_computed
        3. Update stamina/health/morale
        4. Add/remove status tags (max 8, mutex overwrite for higher priority)
        5. Consume items (deduct from inventory)
        6. Add memories
        7. Update relationships
        8. Persist (via persistence layer)
        9. Return new state
        """
        # === Step 1: basic input validation (no heavy ChoiceValidator here) ===
        if not isinstance(player_input, dict):
            raise ValueError("player_input must be a dict")
        if not isinstance(scene_output, dict):
            raise ValueError("scene_output must be a dict")

        # Sanity-check the player_input's character_id matches ours if present.
        input_cid = player_input.get("character_id")
        if input_cid is not None and input_cid != self.character_id:
            raise ValueError(
                f"player_input.character_id '{input_cid}' does not match "
                f"state machine's character_id '{self.character_id}'"
            )

        # === Step 2: pull the precomputed state change ===
        # The scene agent wraps the calculator's output in
        # scene_output["state_change_computed"]. Tolerate both shapes:
        #   - {"state_change_computed": {...}} (production)
        #   - {"stamina": ..., "health": ...} (raw calculator output)
        state_change = scene_output.get("state_change_computed") or scene_output

        # === Step 3: stamina / health / morale ===
        self._apply_physical_mental(state_change)

        # === Step 4: status tags (with mutex eviction) ===
        self._apply_status_tags(state_change)

        # === Step 5: consume items ===
        self._apply_item_consumption(state_change)

        # === Step 6: add memories ===
        self._apply_memories(state_change)

        # === Step 7: relationships (with validation) ===
        self._apply_relationships(state_change)

        # Bookkeeping
        self.round += 1
        self.state["round"] = self.round
        self.state["updated_at"] = datetime.now(UTC).isoformat().replace('+00:00', 'Z')
        self.updated_at = datetime.now(UTC)

        # === Step 8: persist (sync wrapper around async persistence) ===
        # The state machine is sync by design (it has no I/O of its own);
        # persistence.save_character is async, so we hop into asyncio briefly.
        # If we're already inside an event loop (e.g. FastAPI handler), the
        # caller can pass _async_persist to skip this hop.
        async_persist = scene_output.get("_async_persist")
        if async_persist is not None:
            # Caller is in an async context and will persist themselves
            pass
        else:
            self._persist_sync()

        # === Step 9: return new state ===
        return self.get_state()

    # --------------------------------------------------------------------
    # Internal: persist
    # --------------------------------------------------------------------

    def _persist_sync(self) -> None:
        """
        Run ``persistence.save_character`` from a sync context. We try the
        cheap path first (no running loop) and only spin up a loop if we
        genuinely don't have one.
        """
        import asyncio
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is None:
            # Sync path: run to completion in a fresh loop.
            asyncio.run(persistence.save_character(self.state))
        else:
            # Already inside an async context ??schedule a background task
            # and let the loop drive it. The character_state has already been
            # mutated, so even if the persistence call is delayed briefly,
            # the in-memory state is correct.
            running_loop.create_task(persistence.save_character(self.state))

    # --------------------------------------------------------------------
    # Internal: stamina / health / morale
    # --------------------------------------------------------------------

    def _apply_physical_mental(self, state_change: Dict[str, Any]) -> None:
        """Apply the stamina/health/morale transitions from state_change."""
        physical = self.state.setdefault("physical", {})
        mental = self.state.setdefault("mental", {})

        stamina = state_change.get("stamina")
        if isinstance(stamina, dict):
            new_stamina = stamina.get("new")
            if new_stamina:
                # Use the schema field name (stamina_level), but fall back to
                # the bare "stamina" key for legacy states.
                if "stamina_level" in physical or "stamina_level" in self.state:
                    physical["stamina_level"] = new_stamina
                else:
                    physical["stamina"] = new_stamina

        health = state_change.get("health")
        if isinstance(health, dict):
            new_health = health.get("new")
            if new_health:
                if "health_status" in physical or "health_status" in self.state:
                    physical["health_status"] = new_health
                else:
                    physical["health"] = new_health

        morale = state_change.get("morale")
        if isinstance(morale, dict):
            new_morale = morale.get("new")
            if new_morale:
                if "morale_level" in mental or "morale_level" in self.state:
                    mental["morale_level"] = new_morale
                else:
                    mental["morale"] = new_morale

    # --------------------------------------------------------------------
    # Internal: status tags
    # --------------------------------------------------------------------

    def _apply_status_tags(self, state_change: Dict[str, Any]) -> None:
        """
        Add new tags, remove specified tags, and enforce the max-tags cap via
        mutex eviction (drop the tag with the lowest priority, breaking ties
        by insertion order ??earlier tag loses).

        Tags also accept a `priority` map inline via:
            new_status_tags: [ {"name": "wounded", "priority": 8}, "poisoned" ]
        or a plain list of strings (default priority 5).
        """
        physical = self.state.setdefault("physical", {})
        effects: List[str] = list(physical.get("active_effects", []) or [])

        # Remove specified tags first
        removed = state_change.get("removed_status_tags") or []
        for tag in removed:
            if tag in effects:
                effects.remove(tag)
            self.tag_priorities.pop(tag, None)

        # Normalize new_status_tags into a list of (name, priority) tuples
        new_tags_raw = state_change.get("new_status_tags") or []
        new_tags: List[tuple] = []
        for entry in new_tags_raw:
            if isinstance(entry, dict):
                name = entry.get("name") or entry.get("tag")
                priority = int(entry.get("priority", DEFAULT_TAG_PRIORITY))
            else:
                name = str(entry)
                priority = DEFAULT_TAG_PRIORITY
            if not name:
                continue
            new_tags.append((name, priority))

        # Add new tags, evicting lowest-priority existing tags if needed
        max_tags = self.get_max_tags()
        for name, priority in new_tags:
            if name in effects:
                # Already present ??update its priority in case it changed
                self.tag_priorities[name] = priority
                continue

            if len(effects) >= max_tags:
                # Find the lowest-priority tag. Use insertion order as the
                # tiebreaker (older loses).
                victim_idx = 0
                victim_key: Optional[tuple] = None
                for idx, existing in enumerate(effects):
                    existing_prio = self.tag_priorities.get(existing, DEFAULT_TAG_PRIORITY)
                    key = (existing_prio, idx)  # lower = worse
                    if victim_key is None or key < victim_key:
                        victim_key = key
                        victim_idx = idx
                victim = effects.pop(victim_idx)
                self.tag_priorities.pop(victim, None)

            effects.append(name)
            self.tag_priorities[name] = priority

        physical["active_effects"] = effects

    # --------------------------------------------------------------------
    # Internal: item consumption
    # --------------------------------------------------------------------

    def _apply_item_consumption(self, state_change: Dict[str, Any]) -> None:
        """
        Deduct consumed items from inventory. Items with quantity 0 are
        removed. Tolerates multiple formats:
            - [{"item_id": "potion", "quantity": 1}]
            - {"item_id": "potion", "quantity": 1}
            - {"potion": 1}  (legacy map)
        """
        consumed = state_change.get("items_consumed") or []
        if not consumed:
            return

        inventory = self.state.setdefault("inventory", {})
        items: List[Dict[str, Any]] = list(inventory.get("items", []) or [])

        # Normalize to list of (item_id, quantity)
        entries: List[tuple] = []
        for entry in consumed:
            if isinstance(entry, dict):
                item_id = entry.get("item_id") or entry.get("id") or entry.get("name")
                qty = int(entry.get("quantity", entry.get("qty", 1)))
            elif isinstance(entry, str):
                # Just a bare item_id: assume quantity 1
                item_id, qty = entry, 1
            else:
                continue
            if not item_id:
                continue
            entries.append((str(item_id), qty))

        for item_id, qty in entries:
            for slot in items:
                if slot.get("item_id") == item_id:
                    slot["quantity"] = max(0, int(slot.get("quantity", 0)) - qty)
                    break

        # Remove slots that hit zero
        items = [s for s in items if int(s.get("quantity", 0)) > 0]
        inventory["items"] = items

    # --------------------------------------------------------------------
    # Internal: memories
    # --------------------------------------------------------------------

    def _apply_memories(self, state_change: Dict[str, Any]) -> None:
        """Append new memory strings; dedupe exact repeats."""
        new_memories = state_change.get("new_memories") or []
        if not new_memories:
            return
        memories: List[str] = list(self.state.get("memories", []) or [])
        existing = set(memories)
        for mem in new_memories:
            if mem not in existing:
                memories.append(mem)
                existing.add(mem)
        self.state["memories"] = memories

    # --------------------------------------------------------------------
    # Internal: relationships
    # --------------------------------------------------------------------

    def _apply_relationships(self, state_change: Dict[str, Any]) -> None:
        """
        Update or insert relationship levels. Supports:
            - [{"npc_id": "npc_a", "level": "friendly"}]
            - {"npc_a": "friendly"}  (legacy map)

        Invalid level values raise ValueError (per task spec).
        """
        rel_changes = state_change.get("relationship_changes")
        if not rel_changes:
            return

        rels: Dict[str, str] = dict(self.state.get("relationships", {}) or {})

        entries: List[tuple] = []
        if isinstance(rel_changes, dict):
            entries = [(str(k), str(v)) for k, v in rel_changes.items()]
        elif isinstance(rel_changes, list):
            for entry in rel_changes:
                if isinstance(entry, dict):
                    npc_id = entry.get("npc_id") or entry.get("id")
                    level = entry.get("level") or entry.get("value")
                    if npc_id and level:
                        entries.append((str(npc_id), str(level)))

        for npc_id, level in entries:
            if level not in RELATIONSHIP_LEVELS:
                raise ValueError(
                    f"Invalid relationship level '{level}' for npc '{npc_id}'. "
                    f"Allowed: {sorted(RELATIONSHIP_LEVELS)}"
                )
            rels[npc_id] = level

        self.state["relationships"] = rels

    # --------------------------------------------------------------------
    # Status tag direct API (preserved from prior skeleton)
    # --------------------------------------------------------------------

    def add_status_tag(self, tag: str, priority: int = DEFAULT_TAG_PRIORITY, ttl: Optional[int] = None) -> bool:
        """
        Add a status tag to the character.
        Max 8 tags. Mutex overwrite (higher priority wins; ties ??newest wins).
        """
        physical = self.state.setdefault("physical", {})
        effects: List[str] = list(physical.get("active_effects", []) or [])

        if tag in effects:
            # Update priority
            self.tag_priorities[tag] = max(priority, self.tag_priorities.get(tag, 0))
            self.updated_at = datetime.now(UTC)
            return True

        if len(effects) >= self.get_max_tags():
            # Evict the lowest-priority tag (and break ties by oldest)
            victim_idx = 0
            victim_key: Optional[tuple] = None
            for idx, existing in enumerate(effects):
                ep = self.tag_priorities.get(existing, DEFAULT_TAG_PRIORITY)
                key = (ep, idx)
                if victim_key is None or key < victim_key:
                    victim_key = key
                    victim_idx = idx
            victim = effects.pop(victim_idx)
            self.tag_priorities.pop(victim, None)

        effects.append(tag)
        self.tag_priorities[tag] = priority
        physical["active_effects"] = effects
        self.updated_at = datetime.now(UTC)
        return True

    def remove_status_tag(self, tag: str) -> bool:
        """Remove a status tag."""
        physical = self.state.get("physical", {})
        effects: List[str] = list(physical.get("active_effects", []) or [])
        if tag in effects:
            effects.remove(tag)
            physical["active_effects"] = effects
            self.tag_priorities.pop(tag, None)
            self.updated_at = datetime.now(UTC)
            return True
        return False

__all__ = [
    "CharacterStateMachine",
    "MAX_TAGS_DEFAULT",
    "DEFAULT_TAG_PRIORITY",
    "RELATIONSHIP_LEVELS",
]
