"""
Connection Registry (v3.2 — cloud-LLM hardened)
=================================================
Tracks active WebSocket connections + per-character in-memory inflight flags.

NEW in v3.2 (Q7 hardening for full-cloud LLM):
  - inflight_flags: set[str] of character_ids with active LLM task
  - submit_action(): atomic in-memory check + flag acquire
  - In-memory interception BEFORE DB write (microsecond-level anti-burst)
  - Timeout safety: flag auto-released if task crashes (via finally)

Design rationale:
  - set() operations are atomic under CPython GIL
  - No asyncio.Lock needed for the flag check itself
  - Burst protection works even before DB is touched
  - Crash-safe via try/finally
"""
import asyncio
import logging
import time

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionRegistry:
    """Tracks active WebSocket connections + inflight action flags."""

    def __init__(self, inflight_timeout_seconds: int = 60):
        # character_id -> dict of connection_id -> websocket
        self._connections: dict[str, dict[str, WebSocket]] = {}
        # character_id -> whether currently controlled by an active player
        self._player_controlled: dict[str, bool] = {}
        # Q7: In-memory anti-burst lock (set is atomic under GIL)
        self._inflight_flags: set = set()
        # Track when flag was acquired (for stale-flag detection)
        self._inflight_since: dict[str, float] = {}
        self._inflight_timeout = inflight_timeout_seconds
        # Phase L2-I/Phase B: character_id -> scene_id mapping so we can
        # broadcast to everyone in the same scene (cross-player).
        self._character_to_scene: dict[str, str] = {}
        self._lock = asyncio.Lock()

    # ============================================
    # Connection management
    # ============================================

    async def register(
        self,
        character_id: str,
        connection_id: str,
        websocket: WebSocket,
        scene_id: str | None = None,
    ) -> None:
        async with self._lock:
            if character_id not in self._connections:
                self._connections[character_id] = {}
            self._connections[character_id][connection_id] = websocket
            self._player_controlled[character_id] = True
            if scene_id is not None:
                self._character_to_scene[character_id] = scene_id
            logger.info(
                f"[Registry] Registered {connection_id} for {character_id} "
                f"(scene={scene_id}). Active: {len(self._connections[character_id])}"
            )

    async def set_scene(self, character_id: str, scene_id: str) -> None:
        """Update the character-to-scene mapping when a character
        changes scenes (e.g. after a successful action that advances
        the scene)."""
        async with self._lock:
            self._character_to_scene[character_id] = scene_id

    async def unregister(
        self,
        character_id: str,
        connection_id: str,
    ) -> None:
        async with self._lock:
            if character_id in self._connections:
                self._connections[character_id].pop(connection_id, None)
                if not self._connections[character_id]:
                    del self._connections[character_id]
                    self._player_controlled[character_id] = False
                    self._character_to_scene.pop(character_id, None)
                    logger.info(f"[Registry] {character_id} fully disconnected -> NPC mode")

    async def is_player_controlled(self, character_id: str) -> bool:
        async with self._lock:
            return self._player_controlled.get(character_id, False)

    async def broadcast(self, character_id: str, message: dict) -> int:
        async with self._lock:
            connections = list(self._connections.get(character_id, {}).values())
        if not connections:
            return 0
        sent = 0
        for ws in connections:
            try:
                await ws.send_json(message)
                sent += 1
            except Exception as e:
                logger.warning(f"[Registry] Send to {character_id} failed: {e}")
        return sent

    # ============================================
    # Phase L2-I/Phase B: cross-player broadcast
    # ============================================

    async def broadcast_to_scene(
        self,
        scene_id: str,
        message: dict,
        exclude_character_id: str | None = None,
    ) -> int:
        """Send a message to every connected character currently in
        the given scene. Optionally exclude the actor (so the actor
        doesn't receive their own broadcast twice).

        Returns the number of messages successfully sent.
        """
        async with self._lock:
            # Snapshot: which characters are in this scene?
            targets: list[tuple[str, WebSocket]] = []
            for char_id, ws_dict in self._connections.items():
                if self._character_to_scene.get(char_id) != scene_id:
                    continue
                if exclude_character_id and char_id == exclude_character_id:
                    continue
                for ws in ws_dict.values():
                    targets.append((char_id, ws))

        sent = 0
        for char_id, ws in targets:
            try:
                await ws.send_json(message)
                sent += 1
            except Exception as e:
                logger.warning(
                    f"[Registry] Scene broadcast to {char_id} failed: {e}"
                )
        return sent

    async def characters_in_scene(self, scene_id: str) -> list[str]:
        """List all character_ids currently in this scene."""
        async with self._lock:
            return [
                cid
                for cid, sid in self._character_to_scene.items()
                if sid == scene_id and cid in self._connections
            ]

    # ============================================
    # Q7: In-flight action interception
    # ============================================

    def try_acquire_inflight(self, character_id: str) -> bool:
        """
        Try to acquire the in-flight lock for this character.
        Returns True if acquired, False if already in-flight.
        ATOMIC: set.add() is thread-safe under CPython GIL.

        Anti-burst rationale:
          Hacker sends 50 action_submit in 100ms.
          50 concurrent tasks call this method.
          Exactly 1 succeeds, 49 are rejected immediately.
          No DB call, no LLM call, no API quota burned.
        """
        # Stale flag cleanup (defensive — should never trigger due to finally)
        now = time.time()
        if character_id in self._inflight_since:
            age = now - self._inflight_since[character_id]
            if age > self._inflight_timeout:
                logger.warning(
                    f"[Registry] Stale inflight flag for {character_id} "
                    f"({age:.1f}s old) — auto-releasing"
                )
                self._inflight_flags.discard(character_id)
                self._inflight_since.pop(character_id, None)

        # Atomic check-and-set
        if character_id in self._inflight_flags:
            return False
        self._inflight_flags.add(character_id)
        self._inflight_since[character_id] = now
        return True

    def release_inflight(self, character_id: str) -> None:
        """Release the in-flight lock. MUST be called in finally block."""
        self._inflight_flags.discard(character_id)
        self._inflight_since.pop(character_id, None)

    def is_inflight(self, character_id: str) -> bool:
        return character_id in self._inflight_flags

    def inflight_stats(self) -> dict:
        return {
            "total_inflight": len(self._inflight_flags),
            "characters_inflight": list(self._inflight_flags),
            "oldest_age_seconds": (
                max(time.time() - t for t in self._inflight_since.values())
                if self._inflight_since
                else 0
            ),
        }

    # ============================================
    # Stats
    # ============================================

    def stats(self) -> dict:
        return {
            "active_characters": len(self._connections),
            "total_connections": sum(len(c) for c in self._connections.values()),
            "player_controlled": sum(1 for v in self._player_controlled.values() if v),
            "scenes_active": len(set(self._character_to_scene.values())),
            **self.inflight_stats(),
        }


# Global instance
registry = ConnectionRegistry()
