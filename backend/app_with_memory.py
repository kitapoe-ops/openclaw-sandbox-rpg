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
