"""
Memory-Palace-enabled FastAPI App (Phase C3)
============================================

This module composes a FastAPI app that **includes the Wave 2
production app** (from :mod:`backend.main`) AND wires the Phase C2
``memory_palace_integration_endpoint`` router on top. The result is
a single drop-in ASGI app that exposes every Wave 2 route
(``/api/character/...``, ``/api/scene/...``, ``/health``, ``/ws/...``)
plus the four new ``/memory/...`` endpoints.

Why this file exists (instead of editing ``main.py``)
-----------------------------------------------------
Per the Hard Constraints documented in
``docs/PHASE_C2_SUMMARY.md`` (and inherited by Phase C3), the Wave
2 ``backend/main.py`` is **frozen** — it is owned by Wave 2 and
must not be mutated. To preserve that property while still
shipping an end-to-end demo, this module imports the existing
``app`` instance from :mod:`backend.main` and registers the
memory router via ``app.include_router``.

Run it with::

    uvicorn backend.app_with_memory:app --reload

In demo mode (no DB)::

    DEMO_MODE=true uvicorn backend.app_with_memory:app --reload

Notes
-----
* ``app.include_router`` is **idempotent w.r.t. URL prefix** — the
  router already declares ``prefix="/memory"``, so the resulting
  paths are ``/memory/remember``, ``/memory/recall``,
  ``/memory/{character_id}/{memory_id}`` and ``/memory/health``.
* The ``MemoryPalaceIntegration`` singleton is built lazily on
  the first request (see
  :mod:`backend.memory_palace_integration_endpoint`), so importing
  this module does NOT require Postgres to be reachable.
* The lifespan defined in :mod:`backend.main` is preserved — we
  import the already-constructed ``app`` object, lifespan and all.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, FastAPI, HTTPException

# Reuse the Wave 2 production app (frozen). Importing it also
# triggers its router registrations and lifespan wiring.
from .main import app as _wave2_app

# The Phase C2 router (also frozen).
from .memory_palace_integration_endpoint import (
    router as memory_router,
)
from .scenes_demo import DEMO_STARTER, get_demo_character
from .demo_mode import is_demo_mode

logger = logging.getLogger(__name__)


# ============================================
# Compose: include the memory router
# ============================================
# Idempotent: include_router won't double-register if this module
# is imported twice. FastAPI silently overwrites same-prefix
# routes only if their path+method collide; ours are unique.
_wave2_app.include_router(
    memory_router,
    tags=["memory-palace"],
)

# ============================================
# E1: real /api/action/process endpoint (resolves D4 M3 finding #2)
# ============================================
# Per the M3-as-R1 audit (docs/AUDIT_D4_M3.json finding #2),
# ``backend/api/action.py:submit_action`` is a documented echo —
# the demo.html HTTP fallback posted to it and got back an echo,
# leaving the user staring at a green "SUBMITTED" badge with no
# actual state change. To resolve the only remaining E-blocker from
# that audit, we ship a *second* action endpoint
# ``POST /api/action/process`` backed by the new
# :class:`backend.api.action_processor.ActionProcessor`. The legacy
# ``/api/action/submit`` echo is preserved bit-for-bit (the file
# is frozen).
#
# The router is intentionally on a different module so the wire-up
# mirrors the D4 v2 ``/api/character-list/`` pattern: a *new*
# router on this composed app, not a modification of a frozen one.

from .api.action_processor import (  # noqa: E402
    LLMUnavailableError,
    ProcessActionRequest,
    ProcessActionResponse,
    build_default_processor,
)

_e1_router = APIRouter(prefix="/api", tags=["e1-action-processor"])


# We build the processor once at import-time. It contains an
# ``InMemoryTurnSystem`` and an LLMClient chosen by env (mock by
# default). For tests that need hermetic behaviour, they construct
# their own ``ActionProcessor`` instance and patch the dependency
# — see :mod:`backend.tests.test_action_processor`.
_e1_processor = build_default_processor()


@_e1_router.post(
    "/action/process",
    response_model=ProcessActionResponse,
    responses={
        400: {"description": "Invalid verb (not in whitelist)"},
        500: {"description": "LLM client failed"},
    },
)
async def process_action_endpoint(
    req: ProcessActionRequest,
) -> ProcessActionResponse:
    """Process a real player action via HTTP (E1).

    This is the HTTP analogue of the WebSocket ``/ws/game/{id}``
    handler. It runs the full pipeline (validate → physics lock →
    LLM narrative → memory persist → turn update) and returns the
    generated narrative + side-effects.

    Replaces the demo.html "SUBMITTED" silent-echo path.
    """
    try:
        result = await _e1_processor.process(
            character_id=req.character_id,
            verb=req.verb,
            target=req.target,
            args=req.args,
        )
    except LLMUnavailableError as exc:
        # Translate the typed error into an HTTP 500 with a useful
        # detail. FastAPI will JSON-serialize the detail.
        raise HTTPException(
            status_code=500,
            detail=f"LLM unavailable: {exc}",
        ) from exc
    return ProcessActionResponse(**result)


_wave2_app.include_router(_e1_router)


# ============================================
# D4 v2: list-characters endpoint (resolves Phase E blocker #2)
# ============================================
# Per the M3-as-R1 audit (docs/AUDIT_D4_M3.json finding #5), the
# frontend hardcoded ``CHARACTER_ID = 'char_demo_player'`` because
# ``backend/api/character.py`` has no list endpoint and the file is
# frozen. Rather than touching the frozen API router, we add a new
# /api/character-list/ route here on the composed app — it returns
# the available characters in demo mode (and a stub in full mode)
# so the frontend can build a picker without backend changes.
#
# NOTE: this is intentionally on a *different* path prefix to
# avoid colliding with the existing /api/character/ routes already
# mounted from backend/api/character.py.
_d4_list_router = APIRouter(prefix="/api", tags=["d4-v2"])


@_d4_list_router.get("/character-list/", response_model=List[Dict[str, Any]])
async def list_characters() -> List[Dict[str, Any]]:
    """List available characters (D4 v2: resolves Phase E blocker #2).

    * Demo mode: returns the single demo starter character.
    * Full mode: queries the DB; falls back to demo starter if DB
      is unreachable or empty.

    Response shape (stable contract for the frontend picker):
        [
          {
            "character_id": "char_demo_player",
            "name": "Aelar (測試角色)",
            "world_id": "world_default",
            "current_scene_id": "loc_phandalin_town",
            "is_alive": true,
            "is_npc_mode": false,
            "source": "demo"  # or "db"
          }
        ]
    """
    if is_demo_mode():
        demo = get_demo_character(DEMO_STARTER["character_id"])
        if demo is None:
            # Should never happen — DEMO_STARTER is the canonical
            # fallback. Be defensive anyway.
            raise HTTPException(status_code=500, detail="DEMO_STARTER missing")
        return [
            {
                "character_id": demo["character_id"],
                "name": demo["name"],
                "world_id": demo["world_id"],
                "current_scene_id": demo["current_scene_id"],
                "is_alive": demo["is_alive"],
                "is_npc_mode": demo["is_npc_mode"],
                "source": "demo",
            }
        ]

    # Full mode — best-effort DB query, fall back to demo starter.
    try:
        from .db import get_db_session
        from .models import CharacterState

        results: List[Dict[str, Any]] = []
        async with get_db_session() as session:
            # ``select(CharacterState)`` would need an extra import;
            # we use ``session.execute`` with a typed select for
            # forward-compat with SQLAlchemy 2.x.
            from sqlalchemy import select
            stmt = select(CharacterState).limit(50)
            rows = (await session.execute(stmt)).scalars().all()
            for char in rows:
                results.append(
                    {
                        "character_id": char.character_id,
                        "name": char.name,
                        "world_id": char.world_id,
                        "current_scene_id": char.current_scene_id,
                        "is_alive": char.is_alive,
                        "is_npc_mode": char.is_npc_mode,
                        "source": "db",
                    }
                )
        if results:
            return results
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("list_characters DB query failed: %s", exc)

    # Fallback: at least the demo starter is always usable.
    demo = get_demo_character(DEMO_STARTER["character_id"])
    if demo is None:
        return []
    return [
        {
            "character_id": demo["character_id"],
            "name": demo["name"],
            "world_id": demo["world_id"],
            "current_scene_id": demo["current_scene_id"],
            "is_alive": demo["is_alive"],
            "is_npc_mode": demo["is_npc_mode"],
            "source": "demo-fallback",
        }
    ]


_wave2_app.include_router(_d4_list_router)


# ============================================
# E6a: WebSocket fan-out router for 1-4 player multiplayer
# ============================================
# Per the M3-as-R1 audit (docs/AUDIT_D4_M3.json) the game scope
# allows 1-4 players per scene, but the existing Wave 2 stack
# has only a per-character WebSocket endpoint
# (``/ws/game/{character_id}``). To support multi-player fan-out
# ("player A acts → server pushes the event to players B/C/D in
# the same scene") we ship a *new* connection layer at
# ``/ws/multiplayer/{scene_id}/{player_id}`` plus a server-side
# HTTP ``POST /api/multiplayer/{scene_id}/broadcast`` that
# downstream code (e.g. the action processor in
# :mod:`backend.api.action_processor`) can call to trigger a
# scene-wide push.
#
# The manager itself lives in a new file
# ``backend/ws/multiplayer_router.py`` (not in the protected
# list). We import it lazily here so this module can still be
# imported in unit tests that don't need the WS layer.
from fastapi import WebSocket, WebSocketDisconnect  # noqa: E402
from .ws.multiplayer_router import (  # noqa: E402
    MultiplayerConnectionManager,
    get_multiplayer_manager,
    multiplayer_ws_endpoint,
)
from .scene_multiplayer import (  # noqa: E402
    MultiplayerScene,
    get_scene_registry,
)
from .memory_isolation import (  # noqa: E402
    MemoryIsolationGuard,
    MemoryIsolationError,
    get_isolation_guard,
)

_e6a_router = APIRouter(prefix="/api", tags=["e6a-multiplayer"])


@_e6a_router.post(
    "/multiplayer/{scene_id}/broadcast",
    summary="Server-push broadcast to all players in a scene (E6a)",
    responses={
        200: {"description": "Broadcast delivered to N players"},
    },
)
async def http_broadcast(scene_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
    """Trigger a server-push broadcast to all players in a scene.

    Body shape (arbitrary JSON, passed through ``send_json``):

        {"event": "npc_action", "actor": "npc_gundren", "verb": "speak",
         "narrative": "Gundren leans across the bar..."}

    Response::

        {"scene_id": "loc_phandalin_town", "delivered_to": 3}

    The endpoint is HTTP — it is the *outbound* push from server
    to clients. The *inbound* player action still flows through
    the WebSocket (and from E6b onwards through the action
    pipeline).
    """
    manager = get_multiplayer_manager()
    count = await manager.broadcast_to_scene(scene_id, message)
    return {"scene_id": scene_id, "delivered_to": count}


@_e6a_router.get(
    "/multiplayer/{scene_id}/players",
    summary="List player IDs connected to a scene (E6a)",
)
async def http_list_players(scene_id: str) -> Dict[str, Any]:
    """Read-only inspection of a scene's connected players.

    Returns::

        {"scene_id": "loc_phandalin_town", "players": ["p1", "p2"],
         "count": 2, "max_players": 4}
    """
    manager = get_multiplayer_manager()
    players = manager.get_connected_players(scene_id)
    return {
        "scene_id": scene_id,
        "players": players,
        "count": len(players),
        "max_players": manager._max_players,
    }


@_e6a_router.get(
    "/multiplayer/health",
    summary="Multiplayer manager health (E6a)",
)
async def http_multiplayer_health() -> Dict[str, Any]:
    """Return fan-out router stats: active scenes, connections, by-scene breakdown."""
    return get_multiplayer_manager().health()


_wave2_app.include_router(_e6a_router)


# Register the WebSocket route directly on the composed app
# (FastAPI's ``@app.websocket`` decorator is the canonical pattern;
# we cannot use ``APIRouter.websocket`` because FastAPI 0.110+
# supports it but the frozen Wave 2 stack uses the older syntax,
# so we match the existing style from ``backend/main.py``).
@_wave2_app.websocket("/ws/multiplayer/{scene_id}/{player_id}")
async def multiplayer_ws(
    websocket: WebSocket,
    scene_id: str,
    player_id: str,
) -> None:
    """WebSocket endpoint for 1-4 player multiplayer fan-out (E6a).

    URL: ``ws://host:8000/ws/multiplayer/{scene_id}/{player_id}``

    Server pushes (after accept)::

        {"event": "connected", "scene_id": "...", "player_id": "...",
         "active_players": [...], "max_players": 4}

    On full scene or duplicate player_id, the server sends::

        {"event": "error", "reason": "scene_full" | "duplicate"}

    and closes the socket. Otherwise, every JSON message the
    client sends is echoed back as a ``{"event": "received"}``
    receipt. E6b will replace the echo with the real action
    pipeline + scene broadcast.
    """
    await multiplayer_ws_endpoint(websocket, scene_id, player_id)


# ============================================
# E6b: scene state management + memory isolation
# ============================================
# E6a shipped the connection layer (WebSocket fan-out). E6b
# ships the *game-state* layer: a per-scene registry of
# players + NPCs + a turn queue, and a per-scene memory
# access guard that prevents cross-character leaks. Both
# modules are additive and live in non-frozen files:
#
#   backend/scene_multiplayer.py     (MultiplayerScene, SceneRegistry)
#   backend/memory_isolation.py      (MemoryIsolationGuard, _IsolatedMemoryPalace)
#
# Routes added on this composed app (none mutate frozen files):
#
#   POST /api/scene-multiplayer/{scene_id}/create
#   POST /api/scene-multiplayer/{scene_id}/player/{player_id}/join
#   POST /api/scene-multiplayer/{scene_id}/player/{player_id}/leave
#   GET  /api/scene-multiplayer/{scene_id}/players
#   GET  /api/scene-multiplayer/{scene_id}/npcs
#   POST /api/scene-multiplayer/{scene_id}/turn/enqueue
#   POST /api/scene-multiplayer/{scene_id}/turn/process
#   GET  /api/scene-multiplayer/{scene_id}/turn/queue-size
#   GET  /api/scene-multiplayer/{scene_id}/isolation/check
#   GET  /api/scene-multiplayer/health
#
# The routes are intentionally on a *different* prefix
# (``/api/scene-multiplayer/...``) from the E6a multiplayer
# routes (``/api/multiplayer/...``) so the two layers stay
# composable: E6b is *state*, E6a is *transport*.
_e6b_router = APIRouter(prefix="/api/scene-multiplayer", tags=["e6b-scene-state"])


@_e6b_router.post(
    "/{scene_id}/create",
    summary="Create a multiplayer scene (E6b)",
    responses={200: {"description": "Scene ready (new or existing)"}},
)
async def http_create_scene(
    scene_id: str,
    max_players: int = 4,
    max_npcs: int = 100,
) -> Dict[str, Any]:
    """Idempotent — returns the existing scene if present.

    Hard caps: ``max_players`` defaults to 4, ``max_npcs`` to
    100. The brief accepts an in-memory registry for E6b; a
    Postgres-backed registry is a future refactor (the
    ``SceneRegistry`` class is the seam).
    """
    if max_players < 1 or max_players > 16:
        raise HTTPException(
            status_code=400,
            detail=f"max_players must be in [1, 16], got {max_players}",
        )
    if max_npcs < 1 or max_npcs > 1000:
        raise HTTPException(
            status_code=400,
            detail=f"max_npcs must be in [1, 1000], got {max_npcs}",
        )
    registry = get_scene_registry()
    scene = await registry.get_or_create(
        scene_id, max_players=max_players, max_npcs=max_npcs
    )
    return scene.health()


@_e6b_router.post(
    "/{scene_id}/player/{player_id}/join",
    summary="Add a player to a scene (E6b)",
    responses={
        200: {"description": "Player added"},
        404: {"description": "Scene not found"},
        409: {"description": "Scene full / duplicate / character taken"},
    },
)
async def http_join_scene(
    scene_id: str, player_id: str, character_id: str
) -> Dict[str, Any]:
    """Add a player. Returns 409 if the scene is full, the
    player_id is already in the scene, or the character_id is
    already controlled by another player in the scene.
    """
    registry = get_scene_registry()
    scene = registry.get(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="scene_not_found")
    ok = await scene.add_player(player_id, character_id)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail=(
                "join_rejected: scene_full | duplicate_player | "
                "character_taken"
            ),
        )
    return scene.health()


@_e6b_router.post(
    "/{scene_id}/player/{player_id}/leave",
    summary="Remove a player from a scene (E6b)",
    responses={200: {"description": "Player removed (idempotent)"}},
)
async def http_leave_scene(scene_id: str, player_id: str) -> Dict[str, Any]:
    """Idempotent — removing a non-existent player is a no-op."""
    registry = get_scene_registry()
    scene = registry.get(scene_id)
    if scene is None:
        return {"scene_id": scene_id, "player_id": player_id, "removed": False}
    await scene.remove_player(player_id)
    return {"scene_id": scene_id, "player_id": player_id, "removed": True}


@_e6b_router.get(
    "/{scene_id}/players",
    summary="List players in a scene (E6b)",
)
async def http_list_scene_players(scene_id: str) -> Dict[str, Any]:
    """Read-only player list. Returns 404 if the scene is unknown."""
    registry = get_scene_registry()
    scene = registry.get(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="scene_not_found")
    return {
        "scene_id": scene_id,
        "players": [p.to_dict() for p in scene.get_players()],
        "count": len(scene.get_players()),
        "max_players": scene.max_players,
    }


@_e6b_router.get(
    "/{scene_id}/npcs",
    summary="List NPCs in a scene (E6b)",
)
async def http_list_scene_npcs(scene_id: str) -> Dict[str, Any]:
    """Read-only NPC list (shared by all players in the scene)."""
    registry = get_scene_registry()
    scene = registry.get(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="scene_not_found")
    return {
        "scene_id": scene_id,
        "npcs": [n.to_dict() for n in scene.get_npcs()],
        "count": len(scene.get_npcs()),
        "max_npcs": scene.max_npcs,
    }


@_e6b_router.post(
    "/{scene_id}/turn/enqueue",
    summary="Submit an action to the scene turn queue (E6b)",
)
async def http_enqueue_turn(
    scene_id: str,
    actor_id: str,
    action: Dict[str, Any],
) -> Dict[str, Any]:
    """Submit ``action`` to the scene's turn queue on behalf of
    ``actor_id``. Returns the ``ticket_id`` (UUID4) for
    correlation. The consumer of the queue (E1 action
    processor in the next sub-phase) will ``process_next_turn``
    and route the ticket into the action pipeline.
    """
    registry = get_scene_registry()
    scene = registry.get(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="scene_not_found")
    ticket_id = await scene.enqueue_action(actor_id, action)
    return {
        "scene_id": scene_id,
        "ticket_id": ticket_id,
        "queue_size": scene.get_turn_queue_size(),
    }


@_e6b_router.post(
    "/{scene_id}/turn/process",
    summary="Pop the next action from the scene turn queue (E6b)",
)
async def http_process_next_turn(scene_id: str) -> Dict[str, Any]:
    """Pop and return the head ticket. Returns an empty result
    if the queue is empty (no 404). The actual action
    processing (LLM narrative + memory write + WebSocket
    fan-out) is the consumer's responsibility; this endpoint
    is the *drain* primitive that the action processor will
    call from a periodic background task.
    """
    registry = get_scene_registry()
    scene = registry.get(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="scene_not_found")
    ticket = await scene.process_next_turn()
    if ticket is None:
        return {
            "scene_id": scene_id,
            "ticket": None,
            "queue_size": 0,
        }
    return {
        "scene_id": scene_id,
        "ticket": ticket.to_dict(),
        "queue_size": scene.get_turn_queue_size(),
    }


@_e6b_router.get(
    "/{scene_id}/turn/queue-size",
    summary="Read the turn-queue size (E6b)",
)
async def http_turn_queue_size(scene_id: str) -> Dict[str, Any]:
    """Read-only inspection of the queue depth."""
    registry = get_scene_registry()
    scene = registry.get(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="scene_not_found")
    return {
        "scene_id": scene_id,
        "queue_size": scene.get_turn_queue_size(),
    }


@_e6b_router.get(
    "/{scene_id}/isolation/check",
    summary="Check memory-isolation rule for a requester/target pair (E6b)",
)
async def http_isolation_check(
    scene_id: str,
    requester_id: str,
    target_character_id: str,
    op: str = "read",
) -> Dict[str, Any]:
    """Lightweight authorisation check. Useful for the
    frontend to gate UI elements ("can this player see this
    NPC's lore?") without round-tripping through the memory
    palace.
    """
    if op not in {"read", "write"}:
        raise HTTPException(
            status_code=400,
            detail=f"op must be 'read' or 'write', got {op!r}",
        )
    guard = get_isolation_guard()
    allowed = guard.authorize(
        requester_id, scene_id, target_character_id, op=op
    )
    return {
        "scene_id": scene_id,
        "requester_id": requester_id,
        "target_character_id": target_character_id,
        "op": op,
        "allowed": allowed,
    }


@_e6b_router.get(
    "/health",
    summary="Scene registry health (E6b)",
)
async def http_scene_registry_health() -> Dict[str, Any]:
    """Aggregate stats across all live scenes."""
    return get_scene_registry().health()


_wave2_app.include_router(_e6b_router)


# Re-export under a friendly name so the lifespan / app-state /
# test fixtures all see the same instance. (Alias, not a copy.)
app: FastAPI = _wave2_app


# ============================================
# Startup banner — log all wired routes
# ============================================
def _log_wired_routes(application: FastAPI) -> None:
    """Print a human-readable route table on import.

    The banner is useful in two ways:

    * During local dev, the developer sees every URL the app
      exposes — including the Phase C2 memory endpoints.
    * During automated demos (``backend.demo_integration``), the
      banner is the canonical "the wire-up is complete" signal.
    """
    methods_by_path: dict[str, list[str]] = {}
    for route in application.routes:
        path = getattr(route, "path", None)
        if not path or not path.startswith("/"):
            continue
        methods = getattr(route, "methods", None) or set()
        # ``WebSocket`` routes report ``None`` for methods.
        for m in sorted(methods):
            if m == "HEAD":
                continue  # noisy duplicates
            methods_by_path.setdefault(path, []).append(m)

    lines = ["[app_with_memory] Wired routes:"]
    for path in sorted(methods_by_path):
        methods = ",".join(methods_by_path[path])
        lines.append(f"  {methods:>10s}  {path}")
    logger.info("\n".join(lines))


# Run the banner at import time — this fires once when uvicorn
# loads the module, which is exactly when operators want to see
# what the app exposes.
_log_wired_routes(app)


__all__ = ["app"]
