"""
Connection Registry
====================
Tracks active WebSocket connections by character_id.

Why this exists:
- A character can have multiple WS connections (e.g., player on phone + tablet)
- Disconnected clients still have running LLM tasks
- When a client reconnects, we need to send them pending updates from DB
"""
from typing import Dict, List, Set
from fastapi import WebSocket
import asyncio
import logging
from datetime import datetime
import json

logger = logging.getLogger(__name__)


class ConnectionRegistry:
    """
    Tracks WebSocket connections per character_id.

    Thread-safety: Uses asyncio.Lock for concurrent access.
    Pending updates: Stored in-memory until client reconnects, then flushed.
    For production, consider Redis for cross-process pending updates.
    """

    def __init__(self):
        # character_id -> set of (connection_id, websocket)
        self._connections: Dict[str, Dict[str, WebSocket]] = {}
        # character_id -> list of pending messages (waiting for reconnect)
        self._pending_updates: Dict[str, List[dict]] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        character_id: str,
        connection_id: str,
        websocket: WebSocket,
    ) -> None:
        """Register a new connection for a character."""
        async with self._lock:
            if character_id not in self._connections:
                self._connections[character_id] = {}
            self._connections[character_id][connection_id] = websocket
            logger.info(
                f"[Registry] Registered {connection_id} for {character_id}. "
                f"Active connections for character: {len(self._connections[character_id])}"
            )

    async def unregister(
        self,
        character_id: str,
        connection_id: str,
    ) -> None:
        """Unregister a connection. Does NOT clear pending updates."""
        async with self._lock:
            if character_id in self._connections:
                self._connections[character_id].pop(connection_id, None)
                if not self._connections[character_id]:
                    del self._connections[character_id]
                logger.info(
                    f"[Registry] Unregistered {connection_id} for {character_id}. "
                    f"Remaining: {len(self._connections.get(character_id, {}))}"
                )

    async def get_active_connections(self, character_id: str) -> List[WebSocket]:
        """Get all active WebSocket connections for a character."""
        async with self._lock:
            return list(self._connections.get(character_id, {}).values())

    async def is_connected(self, character_id: str) -> bool:
        """Check if character has any active connection."""
        async with self._lock:
            return character_id in self._connections and bool(self._connections[character_id])

    async def broadcast(
        self,
        character_id: str,
        message: dict,
        save_if_disconnected: bool = True,
    ) -> int:
        """
        Send a message to all active connections for a character.
        If save_if_disconnected is True, save to pending updates for later delivery.
        Returns number of connections message was sent to.
        """
        async with self._lock:
            connections = list(self._connections.get(character_id, {}).values())
            disconnected = character_id not in self._connections or not connections

        if disconnected and save_if_disconnected:
            # Save to pending updates
            if character_id not in self._pending_updates:
                self._pending_updates[character_id] = []
            self._pending_updates[character_id].append(message)
            logger.info(
                f"[Registry] Character {character_id} disconnected. "
                f"Saved pending update (total pending: {len(self._pending_updates[character_id])})"
            )
            return 0

        sent = 0
        for ws in connections:
            try:
                await ws.send_json(message)
                sent += 1
            except Exception as e:
                logger.warning(f"[Registry] Failed to send to one connection: {e}")

        logger.debug(f"[Registry] Broadcast to {sent}/{len(connections)} connections for {character_id}")
        return sent

    async def get_pending_updates(self, character_id: str) -> List[dict]:
        """Get pending updates for a character (called on reconnect)."""
        async with self._lock:
            return list(self._pending_updates.get(character_id, []))

    async def clear_pending_updates(self, character_id: str) -> None:
        """Clear pending updates after they've been sent."""
        async with self._lock:
            self._pending_updates.pop(character_id, None)
            logger.info(f"[Registry] Cleared pending updates for {character_id}")

    def stats(self) -> dict:
        """Return registry statistics (for monitoring)."""
        return {
            "total_characters": len(self._connections),
            "total_connections": sum(len(c) for c in self._connections.values()),
            "characters_with_pending": len(self._pending_updates),
        }


# Global registry instance
registry = ConnectionRegistry()
