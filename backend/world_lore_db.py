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
from typing import Dict, Any, List, Optional
import yaml
import json
from pathlib import Path


class WorldLoreDB:
    """
    Manages world content for a single world.

    Storage:
    - PostgreSQL: structured data (NPCs, items, locations, quests)
    - LanceDB: vector embeddings for semantic search (RAG)

    TODO: Implement full DB integration.
    """

    def __init__(self, world_id: str, world_config_path: Optional[Path] = None):
        self.world_id = world_id
        self.world_config_path = world_config_path
        self.npcs: Dict[str, Any] = {}
        self.items: Dict[str, Any] = {}
        self.locations: Dict[str, Any] = {}
        self.quests: Dict[str, Any] = {}
        self.world_parameters: Dict[str, Any] = {}
        self.attitude_dimensions: Dict[str, Any] = {}
        self.physics_lock_rules: Dict[str, List[str]] = {}

    def load_from_yaml(self, yaml_path: Path) -> bool:
        """
        Load world configuration from YAML file.

        Reference format: docs/SCHEMAS/world_parameter.yaml
        """
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

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

            return True
        except Exception as e:
            print(f"Failed to load world config: {e}")
            return False

    def get_npc(self, npc_id: str) -> Optional[Dict[str, Any]]:
        return self.npcs.get(npc_id)

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self.items.get(item_id)

    def get_location(self, location_id: str) -> Optional[Dict[str, Any]]:
        return self.locations.get(location_id)

    def get_quest(self, quest_id: str) -> Optional[Dict[str, Any]]:
        return self.quests.get(quest_id)

    def get_npcs_in_location(self, location_id: str) -> List[Dict[str, Any]]:
        loc = self.get_location(location_id)
        if not loc:
            return []
        return [self.npcs[npc_id] for npc_id in loc.get("npcs_present", []) if npc_id in self.npcs]

    def get_items_in_location(self, location_id: str) -> List[Dict[str, Any]]:
        loc = self.get_location(location_id)
        if not loc:
            return []
        return [self.items[item_id] for item_id in loc.get("items_present", []) if item_id in self.items]

    def get_world_parameter(self, param_id: str) -> Optional[Dict[str, Any]]:
        return self.world_parameters.get(param_id)

    def get_attitude_dimension(self, dim_id: str) -> Optional[Dict[str, Any]]:
        return self.attitude_dimensions.get(dim_id)

    # ============================================
    # RAG Search (vector-based)
    # ============================================

    def semantic_search(
        self,
        query: str,
        entity_types: List[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search world lore using vector similarity (RAG).

        TODO: Integrate LanceDB.
        """
        raise NotImplementedError("TODO: Implement LanceDB integration")

    def get_context_for_scene(
        self,
        location_id: str,
        character_state: Dict[str, Any],
        world_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build a context object for the Scene Agent.
        Includes relevant NPCs, items, world parameters.
        """
        context = {
            "location": self.get_location(location_id),
            "nearby_npcs": self.get_npcs_in_location(location_id),
            "nearby_items": self.get_items_in_location(location_id),
            "active_world_parameters": {
                p["id"]: p
                for p in self.world_parameters.values()
                if p.get("current_level", 0) > 0
            },
            "eternal_rules": getattr(self, "eternal_rules", []),
        }
        return context
