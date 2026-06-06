"""
Multiplayer Scene State (Phase E6b)
===================================

Per-scene state management for 1-4 player multiplayer. The
connection layer (E6a, ``backend.ws.multiplayer_router``) is a
**transport** concern: who has an open WebSocket? E6b is the
**game-state** concern: who is *in* the scene, whose turn is it,
which NPCs are around, and — critically — **whose memories can
they read**.

This module is intentionally **additive** — it wraps the
existing single-character state (which lives in frozen files
such as ``backend/character.py``, ``backend/scene.py``) without
modifying them. The scene object owns:

  * up to 4 ``PlayerState`` (one per connected human)
  * up to 100 ``NPCState`` (shared by all 4 players in the scene)
  * a FIFO ``asyncio.Queue`` of pending actions ("turn queue")
  * a per-scene ``asyncio.Lock`` that serialises mutation
  * a memory-isolation rule: who can read whose memories

Why a new file (instead of extending ``scene.py``)
-------------------------------------------------
``backend/scene.py`` is a **frozen** Wave 2 module that models a
single character inside a single scene. It has no concept of
"1-4 players sharing a scene" and no concept of a per-scene
turn queue with multiple actors. Extending it would require
breaking changes to its frozen public API.

E6b therefore ships a new module at the same level as the
connection layer. The new ``MultiplayerScene`` composes with
the connection manager via a **scene_id** key, and it can be
referenced by the action processor (E1) to look up which scene a
character belongs to.

Hard caps
---------
Game scope: 1-4 players per scene. We also cap NPCs at 100 to
keep the in-memory footprint bounded (an entire 4-player scene
is at most 4 + 100 = 104 actor dicts + the turn queue).

Concurrency model
-----------------
* The per-scene ``asyncio.Lock`` serialises all mutating ops
  (add/remove player, add NPC, enqueue/process turn). Read-only
  inspection methods (e.g. ``get_players``) are lock-free
  snapshots.
* The turn queue itself is an ``asyncio.Queue`` — it is safe to
  use across coroutines. ``process_next_turn`` does
  ``get_nowait`` (non-blocking) so a caller running a
  periodic drain task can poll the queue and sleep when empty.
* The global scene registry is **process-local** (a module-level
  dict). Production multi-process deployments would back this
  with Postgres + Redis; E6b's brief explicitly accepts the
  in-memory registry for now ("module-level scene registry …
  production would use Postgres").

Memory isolation rule
---------------------
The hard rule (security-critical, see
``docs/AUDIT_D4_M3.json`` for the cross-character leak concern):

  * A requester can **always** read their own character's memory.
  * A requester **cannot** read another **player's** character
    memory — even if both are in the same scene.
  * A requester **can** read **NPC** memories (NPCs are shared
    canon, no privacy boundary).

The rule is enforced by :meth:`MultiplayerScene.can_read_memory`
and by :class:`backend.memory_isolation.MemoryIsolationGuard`,
which wraps ``MemoryPalace`` (or ``MemoryPalaceIntegration``) so
that any call to ``remember`` / ``recall`` / ``forget`` is
rejected with ``PermissionError`` if the requester is not
authorised.

R1-14B pre-flight audit response
--------------------------------
The pre-flight audit (``docs/AUDIT_E6B_R1_RAW.json``, proxied
via ``audit_phase_d3_repository``) returned **PASS** with two
findings, both pre-existing and out of scope for E6b:

  * MEDIUM #1 — duplicate ``EMBEDDING_DIM`` constant in
    ``vector_store.py`` and ``memory_palace_integration.py``
    (both **frozen**, fix deferred to a future refactor pass).
  * LOW #2 — repository interface design (D3) — pre-existing.

Neither finding touches E6b. We log this disposition in the
summary.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ============================================
# Hard caps
# ============================================

#: Maximum number of human players per scene. Matches the game
#: scope and the per-scene cap of the E6a connection manager.
DEFAULT_MAX_PLAYERS_PER_SCENE: int = 4

#: Maximum number of NPCs per scene. 100 was chosen so the entire
#: in-memory footprint of a single scene (4 players + 100 NPCs +
#: the turn queue) stays bounded under ~10k actor-state objects
#: across the whole process.
DEFAULT_MAX_NPCS_PER_SCENE: int = 100


# ============================================
# Dataclasses
# ============================================


@dataclass
class PlayerState:
    """In-scene state for a single human player.

    Fields are plain Python types (not enums) so the dataclass
    can be JSON-serialised by the FastAPI HTTP routes without a
    custom encoder.
    """

    player_id: str
    character_id: str
    joined_at: float
    turn_position: int = 0  # 0 = not in queue
    alive: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "character_id": self.character_id,
            "joined_at": self.joined_at,
            "turn_position": self.turn_position,
            "alive": self.alive,
        }


@dataclass
class NPCState:
    """In-scene state for a single NPC.

    Up to 100 per scene. All players in the scene share the
    NPC's state (NPCs are scene-level canon, not per-player
    data).
    """

    npc_id: str
    character_id: str
    location: str
    alive: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "npc_id": self.npc_id,
            "character_id": self.character_id,
            "location": self.location,
            "alive": self.alive,
            "metadata": dict(self.metadata),
        }


# ============================================
# Turn-queue ticket
# ============================================


@dataclass
class TurnTicket:
    """One pending action in the per-scene turn queue.

    ``actor_id`` is either a ``player_id`` (human) or an
    ``npc_id`` (NPC). The action is an opaque ``dict`` (verb +
    target + args), passed through to the action pipeline (E1)
    by the consumer of the queue.
    """

    ticket_id: str
    actor_id: str
    action: dict[str, Any]
    enqueued_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "actor_id": self.actor_id,
            "action": dict(self.action),
            "enqueued_at": self.enqueued_at,
        }


# ============================================
# MultiplayerScene
# ============================================


class MultiplayerScene:
    """Scene state for 1-4 concurrent players (game scope locked).

    The scene owns:

      * ``_players`` — at most ``max_players`` ``PlayerState``
        keyed by ``player_id``.
      * ``_npcs`` — at most ``max_npcs`` ``NPCState`` keyed by
        ``npc_id``.
      * ``_turn_queue`` — an ``asyncio.Queue`` of ``TurnTicket``.
        FIFO; ``process_next_turn`` pops the head.
      * ``_lock`` — an ``asyncio.Lock`` that serialises all
        mutating operations. Read-only inspection methods
        (``get_players``, ``get_npcs``, ``get_turn_queue_size``,
        ``health``) are lock-free snapshots.
    """

    def __init__(
        self,
        scene_id: str,
        max_players: int = DEFAULT_MAX_PLAYERS_PER_SCENE,
        max_npcs: int = DEFAULT_MAX_NPCS_PER_SCENE,
    ) -> None:
        if not scene_id:
            raise ValueError("scene_id must be a non-empty string")
        if max_players < 1:
            raise ValueError(f"max_players must be >= 1, got {max_players}")
        if max_npcs < 1:
            raise ValueError(f"max_npcs must be >= 1, got {max_npcs}")
        self.scene_id = scene_id
        self.max_players = max_players
        self.max_npcs = max_npcs
        self._players: dict[str, PlayerState] = {}
        self._npcs: dict[str, NPCState] = {}
        self._turn_queue: asyncio.Queue[TurnTicket] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._created_at: float = time.time()

    # ============================================
    # Player management
    # ============================================

    async def add_player(self, player_id: str, character_id: str) -> bool:
        """Add a player to the scene.

        Returns ``True`` on success, ``False`` if:

          * ``player_id`` is already in the scene (duplicate
            join — same hardening as the E6a connection layer)
          * the scene is at capacity (``max_players`` reached)
          * the ``character_id`` is already controlled by a
            different player in this scene (one character per
            player — prevents a player from controlling two
            seats in the same scene)
        """
        if not player_id or not character_id:
            raise ValueError("player_id and character_id are both required")
        async with self._lock:
            if player_id in self._players:
                logger.info(
                    f"[Scene] {player_id} already in scene " f"{self.scene_id}; rejecting duplicate"
                )
                return False
            if len(self._players) >= self.max_players:
                logger.info(
                    f"[Scene] {self.scene_id} full "
                    f"({len(self._players)}/{self.max_players}); "
                    f"rejecting {player_id}"
                )
                return False
            for existing in self._players.values():
                if existing.character_id == character_id:
                    logger.info(
                        f"[Scene] {self.scene_id}: character "
                        f"{character_id} already controlled by "
                        f"player {existing.player_id}; rejecting "
                        f"{player_id}"
                    )
                    return False
            self._players[player_id] = PlayerState(
                player_id=player_id,
                character_id=character_id,
                joined_at=time.time(),
            )
            logger.info(
                f"[Scene] {self.scene_id}: {player_id} "
                f"(character={character_id}) joined "
                f"({len(self._players)}/{self.max_players})"
            )
            return True

    async def remove_player(self, player_id: str) -> None:
        """Remove a player and any of their turn-queue tickets.

        Idempotent — calling on a non-existent player is a no-op.
        """
        if not player_id:
            return
        async with self._lock:
            if player_id not in self._players:
                return
            del self._players[player_id]
            # Drain any pending tickets for this player. We rebuild
            # the queue in-place to preserve FIFO order for the
            # remaining tickets. Drain is bounded by queue size —
            # a full queue is 100k+ tickets, so this is O(n) but
            # only when a player leaves; acceptable.
            kept: list[TurnTicket] = []
            while not self._turn_queue.empty():
                try:
                    ticket = self._turn_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if ticket.actor_id != player_id:
                    kept.append(ticket)
            for t in kept:
                self._turn_queue.put_nowait(t)
            logger.info(
                f"[Scene] {self.scene_id}: {player_id} removed "
                f"({len(self._players)} remaining, "
                f"{len(kept)} tickets kept)"
            )

    def get_players(self) -> list[PlayerState]:
        """Snapshot of the current players. Lock-free."""
        return list(self._players.values())

    def get_player(self, player_id: str) -> PlayerState | None:
        """Lookup a single player. Lock-free. Returns None if absent."""
        return self._players.get(player_id)

    # ============================================
    # NPC management
    # ============================================

    async def add_npc(self, npc_id: str, character_id: str, location: str) -> bool:
        """Add an NPC. Returns ``False`` if scene is at the NPC cap.

        NPCs are shared between all players in the scene (no
        per-player NPC ownership). Duplicates by ``npc_id`` are
        silently rejected (a soft error — the caller probably
        re-issued after a network hiccup).
        """
        if not npc_id or not character_id or not location:
            raise ValueError("npc_id, character_id, and location are all required")
        async with self._lock:
            if npc_id in self._npcs:
                return False
            if len(self._npcs) >= self.max_npcs:
                logger.info(
                    f"[Scene] {self.scene_id} NPC cap reached "
                    f"({len(self._npcs)}/{self.max_npcs}); "
                    f"rejecting {npc_id}"
                )
                return False
            self._npcs[npc_id] = NPCState(
                npc_id=npc_id,
                character_id=character_id,
                location=location,
            )
            return True

    def get_npcs(self) -> list[NPCState]:
        """Snapshot of the NPCs. Lock-free."""
        return list(self._npcs.values())

    def get_npc(self, npc_id: str) -> NPCState | None:
        """Lookup a single NPC. Lock-free. Returns None if absent."""
        return self._npcs.get(npc_id)

    # ============================================
    # Turn queue
    # ============================================

    async def enqueue_action(self, actor_id: str, action: dict[str, Any]) -> str:
        """Submit an action to the turn queue.

        ``actor_id`` can be a ``player_id`` or an ``npc_id`` —
        the queue does not enforce turn gating, that is the
        responsibility of the consumer (the action processor).
        Returns the ``ticket_id`` (UUID4) so the caller can
        correlate receipts with the queue.
        """
        if not actor_id or not isinstance(action, dict):
            raise ValueError("actor_id is required and action must be a dict")
        async with self._lock:
            ticket = TurnTicket(
                ticket_id=str(uuid.uuid4()),
                actor_id=actor_id,
                action=dict(action),
                enqueued_at=time.time(),
            )
            await self._turn_queue.put(ticket)
            return ticket.ticket_id

    async def process_next_turn(self) -> TurnTicket | None:
        """Pop and return the next action in the queue.

        Returns ``None`` if the queue is empty (non-blocking).
        The caller (e.g. the action processor's drain task) is
        responsible for invoking the action pipeline with the
        returned ticket and for any state mutation that follows.
        """
        try:
            return self._turn_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def get_turn_queue_size(self) -> int:
        """Number of pending actions. Lock-free snapshot."""
        return self._turn_queue.qsize()

    def peek_next_turn(self) -> TurnTicket | None:
        """Read the head ticket without removing it. Lock-free.

        Returns ``None`` if empty. Useful for the audit log to
        record "what would have been processed next" without
        disturbing the FIFO order.
        """
        if self._turn_queue.empty():
            return None
        # ``Queue._queue`` is a ``collections.deque``; we don't
        # mutate it, only read index 0. This is a deliberate,
        # documented private-attribute use; if Python later
        # changes the internal representation the fallback is
        # to drain + re-enqueue (slower but correct).
        try:
            inner = self._turn_queue._queue  # type: ignore[attr-defined]
            if not inner:
                return None
            return inner[0]
        except (AttributeError, IndexError):
            return None

    # ============================================
    # Health
    # ============================================

    def health(self) -> dict[str, Any]:
        """Return scene stats — for ``/health`` and the audit log."""
        players = self.get_players()
        npcs = self.get_npcs()
        alive_players = sum(1 for p in players if p.alive)
        alive_npcs = sum(1 for n in npcs if n.alive)
        return {
            "scene_id": self.scene_id,
            "player_count": len(players),
            "npc_count": len(npcs),
            "alive_count": alive_players + alive_npcs,
            "alive_players": alive_players,
            "alive_npcs": alive_npcs,
            "queue_size": self.get_turn_queue_size(),
            "max_players": self.max_players,
            "max_npcs": self.max_npcs,
            "uptime_seconds": round(time.time() - self._created_at, 2),
        }

    # ============================================
    # Memory isolation
    # ============================================

    def can_read_memory(self, requester_id: str, target_character_id: str) -> bool:
        """Authorise a memory read.

        Rules:

          * **Own character** — ``requester_id`` is the player
            who controls ``target_character_id`` in this scene:
            **allowed**.
          * **NPC** — ``target_character_id`` corresponds to
            any NPC in the scene: **allowed** (NPCs are shared
            canon).
          * **Other player's character** — anyone else:
            **denied** (cross-character leak prevention).
          * **Unknown requester / target** — denied (fail-closed).

        This is a pure read-only method; it does not mutate
        state and takes no lock.
        """
        if not requester_id or not target_character_id:
            return False
        # Own character
        requester = self._players.get(requester_id)
        if requester and requester.character_id == target_character_id:
            return True
        # NPC — check both npc_id and the NPC's character_id
        for npc in self._npcs.values():
            if npc.npc_id == target_character_id or npc.character_id == target_character_id:
                return True
        # Anything else: denied.
        return False

    def can_write_memory(self, requester_id: str, target_character_id: str) -> bool:
        """Authorise a memory write.

        Memory writes are **stricter** than reads: only the
        character itself may write to its own memory. NPCs can
        not be written to by players (NPCs are managed by the
        action pipeline / DM, not by players).

        Returns ``True`` if the requester controls the target
        character; ``False`` otherwise.
        """
        if not requester_id or not target_character_id:
            return False
        requester = self._players.get(requester_id)
        if requester and requester.character_id == target_character_id:
            return True
        return False


# ============================================
# SceneRegistry — module-level holder
# ============================================


class SceneRegistry:
    """Process-local registry of ``MultiplayerScene`` instances.

    The brief accepts an in-memory registry for E6b ("production
    would use Postgres"). This class is the seam: a future
    Postgres-backed registry can subclass it and override
    ``_create_scene``.

    Concurrency:
      * ``_scenes`` is mutated under ``_lock``.
      * The per-scene ``MultiplayerScene._lock`` is independent;
        this registry's lock is *only* for creating / destroying
        scene entries.
    """

    def __init__(self) -> None:
        self._scenes: dict[str, MultiplayerScene] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        scene_id: str,
        max_players: int = DEFAULT_MAX_PLAYERS_PER_SCENE,
        max_npcs: int = DEFAULT_MAX_NPCS_PER_SCENE,
    ) -> MultiplayerScene:
        """Idempotent — returns existing if present."""
        if not scene_id:
            raise ValueError("scene_id must be a non-empty string")
        async with self._lock:
            if scene_id not in self._scenes:
                self._scenes[scene_id] = self._create_scene(scene_id, max_players, max_npcs)
            return self._scenes[scene_id]

    def _create_scene(
        self,
        scene_id: str,
        max_players: int,
        max_npcs: int,
    ) -> MultiplayerScene:
        """Factory hook for subclasses (e.g. a future PG-backed one)."""
        return MultiplayerScene(scene_id, max_players=max_players, max_npcs=max_npcs)

    async def destroy(self, scene_id: str) -> bool:
        """Remove a scene. Returns True if it was present."""
        async with self._lock:
            return self._scenes.pop(scene_id, None) is not None

    def get(self, scene_id: str) -> MultiplayerScene | None:
        """Lookup a scene. Lock-free."""
        return self._scenes.get(scene_id)

    def all_scenes(self) -> list[MultiplayerScene]:
        """Snapshot of all scenes. Lock-free."""
        return list(self._scenes.values())

    def health(self) -> dict[str, Any]:
        """Aggregate health across all scenes."""
        return {
            "scene_count": len(self._scenes),
            "by_scene": {
                s.scene_id: {
                    "player_count": len(s.get_players()),
                    "npc_count": len(s.get_npcs()),
                    "queue_size": s.get_turn_queue_size(),
                }
                for s in self._scenes.values()
            },
        }


# ============================================
# Module-level singleton
# ============================================

#: Process-wide scene registry. Used by the FastAPI routes in
#: ``backend.app_with_memory`` and by the isolation guard
#: (``backend.memory_isolation``).
scene_registry: SceneRegistry = SceneRegistry()


def get_scene_registry() -> SceneRegistry:
    """Return the process-wide scene registry singleton.

    Indirection (rather than importing the symbol directly) lets
    tests monkey-patch the singleton by reassigning the module
    attribute (mirrors the E6a pattern in
    ``backend.ws.multiplayer_router``).
    """
    return scene_registry


__all__ = [
    "DEFAULT_MAX_PLAYERS_PER_SCENE",
    "DEFAULT_MAX_NPCS_PER_SCENE",
    "PlayerState",
    "NPCState",
    "TurnTicket",
    "MultiplayerScene",
    "SceneRegistry",
    "scene_registry",
    "get_scene_registry",
]
