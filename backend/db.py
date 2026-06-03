"""
Database Session Layer (Stub)
==============================
TODO: Implement actual SQLAlchemy async session integration with schema.sql

This is a stub showing the API contract that game_socket.py expects.
Implement using SQLAlchemy 2.0 async with the schema in deploy/sql/schema.sql.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DatabaseSession:
    """
    Async database session wrapper.
    Implements the methods called by game_socket.py.
    """

    def __init__(self):
        self._session = None

    async def get_character_state(self, character_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch character state from character_states table.
        Returns dict with: character_id, name, current_scene_id, semantic_profile, is_alive, is_npc_mode
        """
        # TODO: Implement
        # SELECT character_id, name, current_scene_id, semantic_profile, is_alive, is_npc_mode
        # FROM character_states WHERE character_id = ?
        raise NotImplementedError("TODO: Implement DB query")

    async def create_action_history(
        self,
        character_id: str,
        scene_id: str,
        round_number: int,
        player_choice: dict,
        execution_status: str = "PENDING",
    ) -> str:
        """
        Insert new row into action_history.
        Returns the action_id (UUID).
        """
        # TODO: Implement
        # INSERT INTO action_history (character_id, scene_id, round_number, player_choice, execution_status)
        # VALUES (?, ?, ?, ?, ?)
        # RETURNING id
        raise NotImplementedError("TODO: Implement DB insert")

    async def update_action_history(
        self,
        action_id: str,
        execution_status: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        llm_narrative_output: Optional[str] = None,
        llm_choices_output: Optional[dict] = None,
        llm_state_changes: Optional[dict] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Update action_history row by id.
        """
        # TODO: Implement dynamic UPDATE
        raise NotImplementedError("TODO: Implement DB update")

    async def apply_state_changes(
        self,
        character_id: str,
        state_changes: dict,
    ) -> None:
        """
        Apply state_changes to character_states.semantic_profile.
        Uses SemanticGradient rules (no skipping, max ±1 per round).
        """
        # TODO: Implement
        # UPDATE character_states SET semantic_profile = ? WHERE character_id = ?
        raise NotImplementedError("TODO: Implement state change application")

    async def update_character_scene(
        self,
        character_id: str,
        new_scene_id: str,
    ) -> None:
        """
        Update current_scene_id (when player moves to new location).
        """
        # TODO: Implement
        # UPDATE character_states SET current_scene_id = ? WHERE character_id = ?
        raise NotImplementedError("TODO: Implement scene update")

    async def get_latest_action(self, character_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the most recent action for a character (used for reclaim).
        """
        # TODO: Implement
        # SELECT * FROM action_history WHERE character_id = ? ORDER BY submitted_at DESC LIMIT 1
        raise NotImplementedError("TODO: Implement latest action query")

    async def recover_interrupted_actions(self) -> int:
        """
        Called on FastAPI startup.
        Mark all PENDING/PROCESSING actions as INTERRUPTED.
        Returns number of actions recovered.
        """
        # TODO: Implement
        # SELECT recover_interrupted_actions() -- uses SQL function from schema.sql
        raise NotImplementedError("TODO: Implement recovery")

    async def close(self):
        """Close the session."""
        # TODO: Implement session.close()
        pass


def get_db_session() -> DatabaseSession:
    """
    Factory function for database sessions.
    Used by game_socket.py and other modules.
    """
    return DatabaseSession()
