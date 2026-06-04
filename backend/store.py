"""
In-Memory Character & Scene Store
====================================
Lightweight in-process storage for development.
Will be replaced by SQLAlchemy + PostgreSQL in production.

Storage:
- characters: dict[character_id, character_state]
- scenes: dict[character_id, list[scene_output]]
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import threading
import copy


class InMemoryStore:
    """Thread-safe in-memory store for characters + scenes."""

    def __init__(self):
        self._lock = threading.Lock()
        self.characters: Dict[str, Dict[str, Any]] = {}
        self.scenes: Dict[str, List[Dict[str, Any]]] = {}
        self.worlds: Dict[str, Dict[str, Any]] = {}

    def save_character(self, character: Dict[str, Any]) -> None:
        with self._lock:
            character["updated_at"] = datetime.utcnow().isoformat() + "Z"
            self.characters[character["character_id"]] = copy.deepcopy(character)

    def get_character(self, character_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            char = self.characters.get(character_id)
            return copy.deepcopy(char) if char else None

    def list_characters(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [copy.deepcopy(c) for c in self.characters.values()]

    def save_scene(self, character_id: str, scene: Dict[str, Any]) -> None:
        with self._lock:
            if character_id not in self.scenes:
                self.scenes[character_id] = []
            self.scenes[character_id].append(scene)

    def get_scene_history(self, character_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            history = self.scenes.get(character_id, [])
            return [copy.deepcopy(s) for s in history[-limit:]]

    def get_latest_scene(self, character_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            history = self.scenes.get(character_id, [])
            return copy.deepcopy(history[-1]) if history else None

    def load_world(self, world_id: str, world_data: Dict[str, Any]) -> None:
        with self._lock:
            self.worlds[world_id] = copy.deepcopy(world_data)

    def get_world(self, world_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            w = self.worlds.get(world_id)
            return copy.deepcopy(w) if w else None


# Global singleton
store = InMemoryStore()
