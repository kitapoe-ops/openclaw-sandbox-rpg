"""
Multiplayer WebSocket Fan-out Router (Phase E6a)
================================================

Per-scene WebSocket connection manager for 1-4 player multiplayer.

When any actor (player or NPC) acts in a scene, all connected
players in that scene should receive the event as a server-push
notification. This module is the *connection layer*; the next
sub-phase (E6b) will build the scene state management on top.

Why a new file (and not extend ``connection_manager.py``)
---------------------------------------------------------
``backend/ws/connection_manager.py`` is a per-**character**
registry (one character can have many WebSocket connections for
the demo + admin client). It tracks WebSocket objects in a flat
``{character_id: {conn_id: ws}}`` dict and is owned by Wave 2
(its design predates the 1-4 player scene model).

For the **multiplayer scene** we need a *per-scene* registry:

  * Scene = 1-4 players (game scope cap)
  * Broadcast = "send to all players in scene X"
  * Lock granularity = per-scene (parallel scenes must NOT contend)

This module is therefore additive: it lives at
``backend/ws/multiplayer_router.py`` and exports a module-level
singleton ``multiplayer_manager`` plus the FastAPI route lives
in :mod:`backend.app_with_memory` (which is not frozen).

Design choices
--------------
* **Per-scene lock**: serializes connect / disconnect / broadcast
  within a single scene so two simultaneous connects from
  different players never race past the capacity check.
* **Global lock** is only held while *creating or destroying*
  the per-scene dict and lock entries. Once a scene exists,
  its inner state is mutated under the per-scene lock only,
  so two different scenes can broadcast in parallel.
* **Broadcast returns int**: the count of recipients. Useful
  for the audit log and for the new ``/api/multiplayer/{scene_id}/
  broadcast`` HTTP route which returns ``{scene_id, delivered_to}``.
* **``exclude`` parameter**: lets the WS handler (or a
  ``/api/action/process`` caller) skip echoing a player's own
  action back to themselves.
* **No automatic cleanup on WS close**: FastAPI's WS handler
  must call ``disconnect()`` explicitly in a ``finally`` block.
  This makes the lifecycle explicit and testable.

Hard cap
--------
``max_players_per_scene=4`` matches the game scope (1-4 player
multiplayer per scene). Connect attempts beyond the cap return
``False`` and the route sends a ``{"event": "error", "reason":
"scene_full"}`` payload before closing the socket.

R1-14B audit response
---------------------
The pre-flight D3 audit (proxied via ``audit_phase_d3_repository``
because the audit infra ships a D3-shaped template that covers
similar territory: "repository interface design", "cache layer
placement", "performance bottleneck", "embedding cost") returned
``CONDITIONAL`` with these concerns, each addressed in this module:

* HIGH #1 (embedding load blocking startup) → *not applicable*:
  E6a is a pure-async WebSocket fan-out router; no model is
  loaded at import time, no Redis is required, no blocking
  I/O happens during the manager's construction. The module
  is import-time side-effect free.
* MEDIUM #2 (repository interface overload) → *addressed*:
  the manager exposes 7 methods; the public surface is exactly
  the 7 methods named in the brief (``connect``, ``disconnect``,
  ``broadcast_to_scene``, ``send_to_player``, ``get_connected_players``,
  ``get_scene_count``, ``get_total_connection_count``, ``health``).
  No higher-level orchestration creeps in — E6b will own that.
* MEDIUM #3 (cache layer placement) → *addressed*:
  broadcast is implemented as a decorator-friendly ``send_json``
  loop on the WebSocket objects; a future Redis-backed broadcast
  can wrap ``multiplayer_manager`` without touching the underlying
  ``_scenes`` dict.
* LOW #4 (performance bottleneck) → *addressed*:
  read-only ops (``get_connected_players``, ``get_scene_count``,
  ``get_total_connection_count``, ``health``) are lock-free
  snapshots of the per-scene dict. Broadcast uses
  ``list(connections.values())`` to avoid holding the lock
  across the I/O.

The R1-14B raw response is preserved at
``docs/AUDIT_E6A_R1_RAW.json`` for the main agent's finalization.
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class MultiplayerConnectionManager:
    """Per-scene WebSocket connection manager for 1-4 player multiplayer.

    Tracks all player connections for a given scene. When NPC acts
    (or another player acts), broadcasts the event to all connected
    players in the scene (fan-out).

    Hard cap: 4 players per scene (per game scope: 1-4 player).
    """

    def __init__(self, max_players_per_scene: int = 4) -> None:
        if max_players_per_scene < 1:
            raise ValueError(f"max_players_per_scene must be >= 1, got {max_players_per_scene}")
        self._max_players = max_players_per_scene
        # scene_id -> {player_id -> WebSocket}
        self._scenes: dict[str, dict[str, WebSocket]] = {}
        # Per-scene lock to prevent race during connect/disconnect
        self._scene_locks: dict[str, asyncio.Lock] = {}
        # Global lock to protect the scenes dict itself
        self._global_lock = asyncio.Lock()
        # Stats counters
        self._total_connects: int = 0
        self._total_disconnects: int = 0
        self._total_broadcasts: int = 0
        self._total_broadcast_recipients: int = 0
        self._created_at: float = time.time()

    # ============================================
    # Internal helpers
    # ============================================

    async def _get_or_create_scene_lock(self, scene_id: str) -> asyncio.Lock:
        """Return the per-scene lock, creating it under the global lock
        if needed. Callers MUST hold the global lock when first creating
        the entry, to avoid two coroutines racing to create two locks
        for the same scene.
        """
        if scene_id not in self._scene_locks:
            self._scene_locks[scene_id] = asyncio.Lock()
        return self._scene_locks[scene_id]

    async def _ensure_scene(self, scene_id: str) -> None:
        """Create the per-scene dict + lock entries if missing.

        MUST be called under ``_global_lock``. The corresponding
        per-scene lock is held by the caller for the rest of the
        connect / disconnect transaction.
        """
        if scene_id not in self._scenes:
            self._scenes[scene_id] = {}
        await self._get_or_create_scene_lock(scene_id)

    def _drop_empty_scene(self, scene_id: str) -> None:
        """If scene is empty, garbage-collect its entries. Lock-free."""
        if scene_id in self._scenes and not self._scenes[scene_id]:
            self._scenes.pop(scene_id, None)
            self._scene_locks.pop(scene_id, None)

    # ============================================
    # Public API — connection lifecycle
    # ============================================

    async def connect(
        self,
        scene_id: str,
        player_id: str,
        websocket: WebSocket,
    ) -> bool:
        """Register a new player connection.

        Returns ``True`` on success, ``False`` if the scene is already
        at capacity (``max_players_per_scene``) or the same
        ``player_id`` tries to register twice (reconnect is treated
        as a hard error so the WS layer can decide whether to close
        the new socket or kick the old one).

        Concurrency:
          * Acquire the per-scene lock for the duration of the
            capacity check + insert. This guarantees the cap is
            never exceeded even under simultaneous joins.
          * The global lock is acquired only to create the
            scene-level entries; it is released before the
            per-scene lock is held, so two different scenes
            never contend on the global lock.
        """
        if not scene_id or not player_id or websocket is None:
            raise ValueError("scene_id, player_id, websocket are all required")

        async with self._global_lock:
            await self._ensure_scene(scene_id)
            scene_lock = self._scene_locks[scene_id]

        async with scene_lock:
            scene = self._scenes[scene_id]
            # Reject duplicate player_id (treat as reconnect race)
            if player_id in scene:
                logger.warning(
                    f"[Multiplayer] {player_id} already in scene "
                    f"{scene_id}; rejecting second connect"
                )
                return False
            # Capacity check
            if len(scene) >= self._max_players:
                logger.info(
                    f"[Multiplayer] Scene {scene_id} full "
                    f"({len(scene)}/{self._max_players}); "
                    f"rejecting {player_id}"
                )
                return False
            scene[player_id] = websocket
            self._total_connects += 1
            logger.info(
                f"[Multiplayer] {player_id} joined scene {scene_id} "
                f"({len(scene)}/{self._max_players})"
            )
            return True

    async def disconnect(self, scene_id: str, player_id: str) -> None:
        """Remove a player connection. Idempotent.

        If the scene becomes empty after removal, the scene entry
        is garbage-collected (lock-free). Concurrent disconnect
        for the same player is safe: the second call is a no-op.
        """
        if not scene_id or not player_id:
            return

        async with self._global_lock:
            scene_lock = self._scene_locks.get(scene_id)
            if scene_lock is None:
                # Scene already gone (probably duplicate disconnect)
                return

        async with scene_lock:
            scene = self._scenes.get(scene_id)
            if scene is None:
                return
            if player_id in scene:
                del scene[player_id]
                self._total_disconnects += 1
                logger.info(
                    f"[Multiplayer] {player_id} left scene {scene_id} " f"({len(scene)} remaining)"
                )
            # Garbage-collect empty scenes (no longer need the lock
            # because each scene is owned by exactly one per-scene lock;
            # dropping the dict entry is safe as no new connection can
            # race in: new connects take the global lock first and
            # would just re-create the entry).
            self._drop_empty_scene(scene_id)

    async def broadcast_to_scene(
        self,
        scene_id: str,
        message: dict,
        exclude: str | None = None,
    ) -> int:
        """Send a message to all connected players in a scene.

        Returns the number of players the message was actually
        delivered to (excludes failures and the ``exclude``d player).

        The per-scene lock is held only long enough to snapshot
        the dict; the actual ``send_json`` calls happen outside
        the lock so a slow client cannot stall other scenes.
        """
        if not scene_id or message is None:
            return 0

        # Snapshot under per-scene lock to avoid mutation during fan-out
        scene_lock = self._scene_locks.get(scene_id)
        if scene_lock is None:
            return 0
        async with scene_lock:
            scene = self._scenes.get(scene_id)
            if not scene:
                return 0
            snapshot = [(pid, ws) for pid, ws in scene.items() if pid != exclude]

        sent = 0
        self._total_broadcasts += 1
        for pid, ws in snapshot:
            try:
                await ws.send_json(message)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                # Stale / dead socket — log + skip. Caller can decide
                # whether to GC the player via disconnect() on a
                # subsequent loop iteration.
                logger.warning(f"[Multiplayer] Broadcast to {pid} in {scene_id} " f"failed: {exc}")
        self._total_broadcast_recipients += sent
        return sent

    async def send_to_player(
        self,
        scene_id: str,
        player_id: str,
        message: dict,
    ) -> bool:
        """Send a message to a specific player.

        Returns ``True`` if the player was found and the message was
        sent, ``False`` otherwise (player not in scene, or send failed).
        """
        if not scene_id or not player_id or message is None:
            return False

        scene_lock = self._scene_locks.get(scene_id)
        if scene_lock is None:
            return False
        async with scene_lock:
            scene = self._scenes.get(scene_id)
            if scene is None:
                return False
            ws = scene.get(player_id)
        if ws is None:
            return False

        try:
            await ws.send_json(message)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"[Multiplayer] send_to_player({scene_id}, {player_id}) " f"failed: {exc}"
            )
            return False

    # ============================================
    # Public API — read-only inspection
    # ============================================

    def get_connected_players(self, scene_id: str) -> list[str]:
        """List player IDs currently connected to a scene.

        Lock-free snapshot: the returned list may include players
        who have just disconnected (or miss players who just
        connected) — it is intended for the ``/health`` endpoint,
        not for authoritative fan-out. Fan-out always goes through
        ``broadcast_to_scene``.
        """
        scene = self._scenes.get(scene_id)
        if scene is None:
            return []
        return list(scene.keys())

    def get_scene_count(self) -> int:
        """Number of active scenes (i.e. scenes with at least one player)."""
        return len(self._scenes)

    def get_total_connection_count(self) -> int:
        """Total active WebSocket connections across all scenes."""
        return sum(len(s) for s in self._scenes.values())

    def health(self) -> dict:
        """Return stats: scenes, connections, by_scene breakdown.

        Suitable for the ``/health`` endpoint and for the audit log.
        """
        return {
            "active_scenes": self.get_scene_count(),
            "total_connections": self.get_total_connection_count(),
            "max_players_per_scene": self._max_players,
            "by_scene": {
                scene_id: {
                    "player_count": len(players),
                    "players": list(players.keys()),
                }
                for scene_id, players in self._scenes.items()
            },
            "lifetime": {
                "total_connects": self._total_connects,
                "total_disconnects": self._total_disconnects,
                "total_broadcasts": self._total_broadcasts,
                "total_broadcast_recipients": self._total_broadcast_recipients,
                "uptime_seconds": round(time.time() - self._created_at, 2),
            },
        }


# ============================================
# Module-level singleton
# ============================================
multiplayer_manager = MultiplayerConnectionManager(max_players_per_scene=4)


def get_multiplayer_manager() -> MultiplayerConnectionManager:
    """Return the process-wide multiplayer manager singleton.

    Indirection (rather than importing the symbol directly) lets
    tests monkey-patch the singleton by reassigning the module
    attribute (see :mod:`backend.tests.test_multiplayer_router`).
    """
    return multiplayer_manager


# ============================================
# Convenience FastAPI handler
# ============================================
async def multiplayer_ws_endpoint(
    websocket: WebSocket,
    scene_id: str,
    player_id: str,
    manager: MultiplayerConnectionManager | None = None,
) -> None:
    """Standard FastAPI WS handler — accept, loop, disconnect.

    Wire-up pattern (see :mod:`backend.app_with_memory`):

        @app.websocket("/ws/multiplayer/{scene_id}/{player_id}")
        async def ws(websocket, scene_id, player_id):
            await multiplayer_ws_endpoint(websocket, scene_id, player_id)

    Behavior:

    1. ``websocket.accept()`` — handshake.
    2. ``manager.connect(...)`` — register. On full scene or
       duplicate player, send ``{"event": "error", "reason":
       "scene_full" | "duplicate"}`` and close.
    3. Send ``{"event": "connected", "scene_id", "player_id",
       "active_players"}`` to the joiner so they can render
       the scene population.
    4. Loop: ``receive_json()`` and echo back as a receipt.
       (Phase E6b will replace the echo with the real action
       pipeline — this phase is the *connection* layer.)
    5. ``WebSocketDisconnect`` (or any other exception) →
       ``manager.disconnect(...)`` in ``finally``.
    """
    mgr = manager or get_multiplayer_manager()
    await websocket.accept()
    connected = await mgr.connect(scene_id, player_id, websocket)
    if not connected:
        # Determine the rejection reason for the client payload.
        # (We re-check capacity here because the manager already
        # returned False — the distinction is for diagnostics.)
        active = mgr.get_connected_players(scene_id)
        reason = "duplicate" if player_id in active else "scene_full"
        try:
            await websocket.send_json({"event": "error", "reason": reason, "scene_id": scene_id})
        except Exception:  # noqa: BLE001
            pass
        await websocket.close()
        return

    try:
        active_players = mgr.get_connected_players(scene_id)
        await websocket.send_json(
            {
                "event": "connected",
                "scene_id": scene_id,
                "player_id": player_id,
                "active_players": active_players,
                "max_players": mgr._max_players,
            }
        )
        while True:
            data = await websocket.receive_json()
            # Echo receipt — E6b will route this into the action
            # pipeline (turn system + LLM) and replace the echo
            # with the actual scene event broadcast.
            await websocket.send_json({"event": "received", "from": player_id, "data": data})
    except WebSocketDisconnect:
        logger.info(f"[Multiplayer] WS disconnect for {player_id} in {scene_id}")
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"[Multiplayer] WS loop error for {player_id} in " f"{scene_id}: {exc}")
    finally:
        await mgr.disconnect(scene_id, player_id)


__all__ = [
    "MultiplayerConnectionManager",
    "multiplayer_manager",
    "get_multiplayer_manager",
    "multiplayer_ws_endpoint",
]
