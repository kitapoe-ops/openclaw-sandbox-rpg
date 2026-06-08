"""
World Lore Database
====================
Manages world content: NPCs, items, locations, quests.
Uses both PostgreSQL (structured) and LanceDB (vector search).

Reference: docs/SCHEMAS/world_parameter.yaml
           docs/SCHEMAS/npc.schema.json
           docs/SCHEMAS/item.schema.json
           docs/SCHEMAS/location.schema.json
           docs/SCHEMAS/quest.schema.json
"""
import json
from pathlib import Path
from typing import Any

import yaml


class WorldLoreDB:
    """
    Manages world content for a single world.

    Storage:
    - PostgreSQL: structured data (NPCs, items, locations, quests)
    - LanceDB: vector embeddings for semantic search (RAG)

    TODO: Implement full DB integration.
    """

    def __init__(self, world_id: str, world_config_path: Path | None = None):
        self.world_id = world_id
        self.world_config_path = world_config_path
        self.npcs: dict[str, Any] = {}
        self.items: dict[str, Any] = {}
        self.locations: dict[str, Any] = {}
        self.quests: dict[str, Any] = {}
        self.world_parameters: dict[str, Any] = {}
        self.attitude_dimensions: dict[str, Any] = {}
        self.physics_lock_rules: dict[str, list[str]] = {}
        self.starting_story: dict[str, Any] = {}

    def _load_config_dict(self, config: dict[str, Any]) -> None:
        """Helper to populate internal dictionaries from a parsed configuration dictionary."""
        # Load eternal rules
        self.eternal_rules = config.get("eternal", {}).get("physical_rules", [])

        # Load world parameters
        for param in config.get("world_parameters", []):
            self.world_parameters[param["id"]] = param

        # Load attitude dimensions
        for dim in config.get("attitude_dimensions", []):
            self.attitude_dimensions[dim["id"]] = dim

        # Load NPCs
        for npc in config.get("npcs", []):
            self.npcs[npc["id"]] = npc

        # Load items
        for item in config.get("items", []):
            self.items[item["id"]] = item

        # Load locations
        for loc in config.get("locations", []):
            self.locations[loc["id"]] = loc

        # Load quests
        for quest in config.get("quests", []):
            self.quests[quest["id"]] = quest

        # Load physics lock rules
        for rule in config.get("physics_lock_rules", {}).get("forbidden_actions", []):
            self.physics_lock_rules[rule["state"]] = rule["forbidden"]

        # Load starting story
        self.starting_story = config.get("starting_story", {})

    def load_from_yaml(self, yaml_path: Path) -> bool:
        """
        Load world configuration from YAML file.

        Reference format: docs/SCHEMAS/world_parameter.yaml
        """
        try:
            with open(yaml_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)
            self._load_config_dict(config)
            return True
        except Exception as e:
            print(f"Failed to load world config from YAML: {e}")
            return False

    def load_from_json(self, json_path: Path) -> bool:
        """Load world configuration from JSON file."""
        try:
            with open(json_path, encoding="utf-8") as f:
                config = json.load(f)
            self._load_config_dict(config)
            return True
        except Exception as e:
            print(f"Failed to load world config from JSON: {e}")
            return False

    def get_npc(self, npc_id: str) -> dict[str, Any] | None:
        return self.npcs.get(npc_id)

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        return self.items.get(item_id)

    def get_location(self, location_id: str) -> dict[str, Any] | None:
        return self.locations.get(location_id)

    def get_quest(self, quest_id: str) -> dict[str, Any] | None:
        return self.quests.get(quest_id)

    def get_npcs_in_location(self, location_id: str) -> list[dict[str, Any]]:
        loc = self.get_location(location_id)
        if not loc:
            return []
        return [self.npcs[npc_id] for npc_id in loc.get("npcs_present", []) if npc_id in self.npcs]

    def get_items_in_location(self, location_id: str) -> list[dict[str, Any]]:
        loc = self.get_location(location_id)
        if not loc:
            return []
        return [
            self.items[item_id] for item_id in loc.get("items_present", []) if item_id in self.items
        ]

    def get_world_parameter(self, param_id: str) -> dict[str, Any] | None:
        return self.world_parameters.get(param_id)

    def get_attitude_dimension(self, dim_id: str) -> dict[str, Any] | None:
        return self.attitude_dimensions.get(dim_id)

    # ============================================
    # RAG Search (vector-based)
    # ============================================

    def semantic_search(
        self,
        query: str,
        entity_types: list[str] = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Search world lore using in-memory keyword matching.

        Production note: This is a placeholder for LanceDB RAG integration.
        For now, returns matches from in-memory entity dicts via simple
        substring scoring (case-insensitive). Acceptable for demo mode.
        """
        if not query:
            return []
        q_lower = query.lower()
        results: list[tuple] = []  # (score, entity)

        # Search in selected entity types (or all)
        type_to_dict = {
            "npc": self.npcs,
            "item": self.items,
            "location": self.locations,
            "quest": self.quests,
        }
        types_to_search = entity_types or list(type_to_dict.keys())

        for etype in types_to_search:
            entity_dict = type_to_dict.get(etype)
            if not entity_dict:
                continue
            for eid, entity in entity_dict.items():
                # Score by keyword matches in name + description
                score = 0
                name = (entity.get("name", "") or "").lower()
                desc = (entity.get("description", "") or "").lower()
                if q_lower in name:
                    score += 3
                if q_lower in desc:
                    score += 1
                # Count word overlaps
                query_words = set(q_lower.split())
                for word in query_words:
                    if len(word) > 2 and word in name:
                        score += 1
                    if len(word) > 2 and word in desc:
                        score += 0.5
                if score > 0:
                    results.append((score, {"type": etype, **entity}))

        # Sort by score desc, return top_k
        results.sort(key=lambda x: -x[0])
        return [r[1] for r in results[:top_k]]

    def get_context_for_scene(
        self,
        location_id: str,
        character_state: dict[str, Any],
        world_state: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Build a context object for the Scene Agent.
        Includes relevant NPCs, items, world parameters.
        """
        context = {
            "location": self.get_location(location_id),
            "nearby_npcs": self.get_npcs_in_location(location_id),
            "nearby_items": self.get_items_in_location(location_id),
            "active_world_parameters": {
                p["id"]: p for p in self.world_parameters.values() if p.get("current_level", 0) > 0
            },
            "eternal_rules": getattr(self, "eternal_rules", []),
        }
        return context
