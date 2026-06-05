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

from fastapi import FastAPI

# Reuse the Wave 2 production app (frozen). Importing it also
# triggers its router registrations and lifespan wiring.
from .main import app as _wave2_app

# The Phase C2 router (also frozen).
from .memory_palace_integration_endpoint import (
    router as memory_router,
)

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
