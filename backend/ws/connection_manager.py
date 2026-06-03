"""
Connection Registry (Simplified v3.0)
======================================
Tracks active WebSocket connections per character_id.

Simplification rationale (Q3):
  - Pending updates are NO LONGER stored in memory
  - On reconnect, client queries DB for latest scene (via REST)
  - Single source of truth = PostgreSQL
"""
from typing import Dict, List
from fastapi import WebSocket
import asyncio
import logging

logger = logging.getLogger(__name__)


class ConnectionRegistry:
    """Tracks active WebSocket connections per character_id."""

    def __init__(self):
        # character_id -> dict of connection_id -> websocket
        self._connections: Dict[str, Dict[str, WebSocket]] = {}
        # character_id -> whether currently controlled by an active player
        self._player_controlled: Dict[str, bool] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        character_id: str,
        connection_id: str,
        websocket: WebSocket,
    ) -> None:
        """Register a new connection. Marks character as player-controlled."""
        async with self._lock:
            if character_id not in self._connections:
                self._connections[character_id] = {}
            self._connections[character_id][connection_id] = websocket
            self._player_controlled[character_id] = True
            logger.info(
                f"[Registry] Registered {connection_id} for {character_id}. "
                f"Active: {len(self._connections[character_id])}"
            )

    async def unregister(
        self,
        character_id: str,
        connection_id: str,
    ) -> None:
        """
        Unregister a connection. Marks character as NPC-controlled if no more connections.
        """
        async with self._lock:
            if character_id in self._connections:
                self._connections[character_id].pop(connection_id, None)
                if not self._connections[character_id]:
                    del self._connections[character_id]
                    self._player_controlled[character_id] = False
                    logger.info(
                        f"[Registry] {character_id} fully disconnected -> NPC mode"
                    )

    async def is_player_controlled(self, character_id: str) -> bool:
        async with self._lock:
            return self._player_controlled.get(character_id, False)

    async def broadcast(self, character_id: str, message: dict) -> int:
        """
        Send a message to all active connections for a character.
        Returns number of connections message was sent to.
        Note: If no active connection, message is DROPPED (caller should persist to DB).
        """
        async with self._lock:
            connections = list(self._connections.get(character_id, {}).values())

        if not connections:
            logger.debug(f"[Registry] No active connection for {character_id}, message dropped")
            return 0

        sent = 0
        for ws in connections:
            try:
                await ws.send_json(message)
                sent += 1
            except Exception as e:
                logger.warning(f"[Registry] Send to {character_id} failed: {e}")

        return sent

    async def get_active_connections(self, character_id: str) -> List[WebSocket]:
        async with self._lock:
            return list(self._connections.get(character_id, {}).values())

    def stats(self) -> dict:
        return {
            "active_characters": len(self._connections),
            "total_connections": sum(len(c) for c in self._connections.values()),
            "player_controlled": sum(1 for v in self._player_controlled.values() if v),
        }


# Global instance
registry = ConnectionRegistry()
