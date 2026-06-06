"""
Memory Palace Integration — FastAPI Endpoints (Phase C2)
========================================================

Exposes a small REST surface over :class:`MemoryPalaceIntegration`
so the rest of the system (and external demos) can drive the
integration end-to-end:

* ``POST /memory/remember`` — store a memory (relational + vector).
* ``POST /memory/recall``   — semantic search, per-character.
* ``DELETE /memory/{character_id}/{memory_id}`` — forget.
* ``GET /memory/health``    — backend liveness.

Wiring model
------------
* This module exports a FastAPI ``router`` (``APIRouter``) that the
  parent app (``main.py``) includes via
  ``app.include_router(memory_palace_integration_endpoint.router, ...)``.
* A module-level :data:`_integration` holds the singleton
  :class:`MemoryPalaceIntegration` instance. It is built lazily on
  the first request via :func:`_get_integration`, so importing this
  module does not require Postgres to be reachable.
* For tests, :func:`set_integration` lets the test fixture inject a
  pre-built instance without touching the database env. This is the
  same "module-level instance + setter" pattern used by
  :mod:`backend.scheduler` (Phase B2).
* The endpoint does NOT modify ``backend/main.py`` (Hard Constraint
  #1). It is a drop-in router.

Error model
-----------
* 400 for input-validation failures (Pydantic does this for us
  via ``Field(..., min_length=...)`` etc.).
* 404 for "memory not found / not yours" (we surface ``False`` from
  :meth:`MemoryPalaceIntegration.forget` as a 404 with a clear
  message).
* 500 is reserved for backend failures (PG/Vector down) — the
  handlers will let the exception bubble so FastAPI's default
  exception handler returns 500.

Embedding dim is fixed at :data:`backend.vector_store.EMBEDDING_DIM`
(384, ``all-MiniLM-L6-v2``). See design doc Q3 resolution.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .memory_palace_integration import (
    MemoryPalaceIntegration,
    SalienceOutOfRangeError,
)
from .persistence_pg import PostgresPersistence
from .vector_store import EMBEDDING_DIM, VectorStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory", tags=["memory-palace"])

# ============================================
# Module-level singleton (lazily initialized)
# ============================================
_integration: MemoryPalaceIntegration | None = None


def set_integration(instance: MemoryPalaceIntegration | None) -> None:
    """Inject a pre-built integration (test fixture hook).

    Pass ``None`` to clear (used by the teardown of the endpoint
    tests). In production, the singleton is built lazily on the
    first request via :func:`_get_integration`.
    """
    global _integration
    _integration = instance


def _get_integration() -> MemoryPalaceIntegration:
    """Lazy builder for the module-level singleton.

    Honors the existing :data:`PERSISTENCE_MODE` env switch:

    * ``"postgres"`` → real Postgres (asyncpg in prod; aiosqlite
      in dev when the URL is ``sqlite+aiosqlite:///...``).
    * ``"memory"`` (default) → fall back to aiosqlite file under
      ``./data/memory_palace_integration.db`` so the endpoint works
      in demo mode without infrastructure. The vector store uses
      its in-memory fallback either way (no LanceDB required).

    We do NOT call ``health()`` here — the first real request will
    trigger schema bootstrap, which keeps cold-start cheap.
    """
    global _integration
    if _integration is not None:
        return _integration

    mode = (os.getenv("PERSISTENCE_MODE") or "").strip().lower()
    if mode == "postgres":
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            raise HTTPException(
                status_code=500,
                detail=(
                    "PERSISTENCE_MODE=postgres but DATABASE_URL is not set. "
                    "Set DATABASE_URL to a SQLAlchemy async URL."
                ),
            )
        persistence = PostgresPersistence(dsn)
    else:
        # Default / demo path — use aiosqlite under ./data. This
        # mirrors the rest of the codebase's "demo mode" pattern.
        data_dir = os.environ.get("SANDBOX_RPG_DATA_DIR", "./data")
        os.makedirs(data_dir, exist_ok=True)
        sqlite_path = os.path.join(data_dir, "memory_palace_integration.db")
        persistence = PostgresPersistence(f"sqlite+aiosqlite:///{sqlite_path}")

    vector_store = VectorStore()
    _integration = MemoryPalaceIntegration(persistence, vector_store)
    return _integration


# ============================================
# Request / Response models
# ============================================
class RememberRequest(BaseModel):
    """POST /memory/remember body."""

    character_id: str = Field(..., min_length=1, max_length=256)
    content: str = Field(..., min_length=1, max_length=4000)
    embedding: list[float] = Field(..., min_length=EMBEDDING_DIM, max_length=EMBEDDING_DIM)
    memory_type: str = Field("episodic", pattern="^(episodic|semantic|procedural)$")
    salience: float = Field(0.5, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None


class RememberResponse(BaseModel):
    """POST /memory/remember response."""

    memory_id: str


class RecallRequest(BaseModel):
    """POST /memory/recall body."""

    character_id: str = Field(..., min_length=1, max_length=256)
    query_embedding: list[float] = Field(..., min_length=EMBEDDING_DIM, max_length=EMBEDDING_DIM)
    k: int = Field(5, ge=1, le=50)
    memory_type: str | None = Field(None, pattern="^(episodic|semantic|procedural)$")
    min_salience: float = Field(0.0, ge=0.0, le=1.0)


class RecallResponse(BaseModel):
    """POST /memory/recall response."""

    results: list[dict[str, Any]]


class ForgetResponse(BaseModel):
    """DELETE /memory/{character_id}/{memory_id} response."""

    deleted: bool
    character_id: str
    memory_id: str


class HealthResponse(BaseModel):
    """GET /memory/health response."""

    postgres: bool
    vector_store: bool


# ============================================
# Routes
# ============================================
@router.post("/remember", response_model=RememberResponse)
async def remember(req: RememberRequest) -> RememberResponse:
    """Store a new memory in both backends.

    Returns the new ``memory_id`` (UUID4 string). The caller can
    later reference it via ``GET /memory/...`` (Phase B/C) or use
    it as a stable handle for a "memory echo" in the Scene Agent
    prompt.
    """
    try:
        memory_id = await _get_integration().remember(
            character_id=req.character_id,
            content=req.content,
            embedding=req.embedding,
            memory_type=req.memory_type,
            salience=req.salience,
            metadata=req.metadata,
        )
    except SalienceOutOfRangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RememberResponse(memory_id=memory_id)


@router.post("/recall", response_model=RecallResponse)
async def recall(req: RecallRequest) -> RecallResponse:
    """Semantic search over a character's memories.

    Returns up to ``k`` results, each shaped::

        {
          "memory_id":   "<uuid4>",
          "content":     "<text>",
          "memory_type": "episodic" | "semantic" | "procedural",
          "salience":    0.0..1.0,
          "similarity":  -1.0..1.0,
          "metadata":    { ... }
        }

    Results are ordered by ``similarity`` (descending).
    """
    try:
        results = await _get_integration().recall(
            character_id=req.character_id,
            query_embedding=req.query_embedding,
            k=req.k,
            memory_type=req.memory_type,
            min_salience=req.min_salience,
        )
    except SalienceOutOfRangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RecallResponse(results=results)


@router.delete(
    "/{character_id}/{memory_id}",
    response_model=ForgetResponse,
)
async def forget(character_id: str, memory_id: str) -> ForgetResponse:
    """Delete a memory, verifying ownership.

    Returns ``{"deleted": true, ...}`` on success. Returns a 404
    with ``deleted: false`` if the memory does not exist or
    belongs to a different character — the caller can treat both
    as "nothing happened" and the 404 is the canonical signal.
    """
    deleted = await _get_integration().forget(character_id, memory_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Memory {memory_id} not found for character "
                f"{character_id} (or ownership check failed)"
            ),
        )
    return ForgetResponse(
        deleted=True,
        character_id=character_id,
        memory_id=memory_id,
    )


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Per-backend liveness probe.

    Always returns 200 — even if one backend is down — so callers
    can read the booleans and degrade gracefully. (FastAPI does
    not have a "200 with a 5xx-shaped body" idiom; we surface
    partial outages via the boolean fields.)
    """
    h = await _get_integration().health()
    return HealthResponse(
        postgres=bool(h.get("postgres", False)),
        vector_store=bool(h.get("vector_store", False)),
    )


__all__ = [
    "router",
    "set_integration",
]
