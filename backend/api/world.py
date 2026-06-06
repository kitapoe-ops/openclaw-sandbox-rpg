"""
World API Endpoints (v3.7 + demo mode fallback)
================================================
Routes:
  GET  /                          — list available worlds
  GET  /{world_id}/state          — get world state (parameters, events)
  GET  /{world_id}/parameters     — alias of /state
  POST /{world_id}/etl            — trigger daily ETL (admin)

Demo mode:
  When `is_demo_mode()` returns True (e.g., no DB reachable), the endpoints
  read from the YAML world loader (`backend/world_lore_loader.py`) instead
  of PostgreSQL. This keeps the API usable for tests and offline dev.

DB mode:
  Unchanged — uses async SQLAlchemy session against the World/WorldParameterState
  models.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException

from ..demo_mode import is_demo_mode
from ..world_lore_loader import world_lore_loader

# DB-mode imports are lazy: we only need them when not in demo mode.
# Importing them at module load is fine (they don't connect), but we
# still guard the actual session usage with is_demo_mode() at runtime.

router = APIRouter()


# ============================================
# Demo mode helpers
# ============================================

# Resolve the worlds/ directory relative to this file, not to the process
# working directory. The CI workflow runs `cd backend && pytest`, which
# would otherwise resolve "worlds" to a non-existent `backend/worlds/`.
# The actual worlds/ dir lives at the repo root: <repo>/worlds/.
# This file is at <repo>/backend/api/world.py, so:
#   __file__ -> backend/api/
#   .parent  -> backend/
#   .parent  -> <repo>/
#   / "worlds" -> <repo>/worlds/
_WORLDS_DIR = Path(__file__).resolve().parent.parent.parent / "worlds"


def _resolve_world_yaml(world_id: str) -> Optional[Path]:
    """
    Map a world_id to a YAML file inside `worlds/`.

    The loader registers by file stem (e.g. `dnd_5e_forgotten_realms.yaml`
    -> `dnd_5e_forgotten_realms`). The YAML's own `world_meta.id` may differ
    (e.g. `dnd_5e_forgotten_realms_phandalin`), so we prefer the file stem
    as the canonical key. We also try the meta-id filename as a fallback.
    """
    candidate = _WORLDS_DIR / f"{world_id}.yaml"
    if candidate.exists():
        return candidate
    # Fallback: scan worlds/ and match by world_meta.id
    if _WORLDS_DIR.exists():
        for yaml_file in _WORLDS_DIR.glob("*.yaml"):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    head = f.read(4096)
                if f"id: \"{world_id}\"" in head or f"id: '{world_id}'" in head:
                    return yaml_file
            except OSError:
                continue
    return None


def _load_yaml_world(world_id: str) -> Optional[Dict[str, Any]]:
    """Read a world YAML directly (cheap one-shot, no lazy loader required)."""
    yaml_path = _resolve_world_yaml(world_id)
    if yaml_path is None:
        return None
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _demo_list_worlds() -> List[Dict[str, Any]]:
    """List worlds from the `worlds/` directory for demo mode."""
    if not _WORLDS_DIR.exists():
        return []
    out: List[Dict[str, Any]] = []
    for yaml_file in sorted(_WORLDS_DIR.glob("*.yaml")):
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                head = f.read(2048)
            world_id = yaml_file.stem
            # Cheap metadata extraction (avoids full YAML parse)
            name = world_id
            version = "unknown"
            description = ""
            try:
                data = yaml.safe_load(head.split("\n# ===", 1)[0])
                if isinstance(data, dict):
                    meta = data.get("world_meta", {}) or {}
                    name = meta.get("name", world_id)
                    version = meta.get("version", "unknown")
                    description = (meta.get("description", "") or "").strip()
                    # Prefer the meta.id when present, but keep the file stem
                    # as the canonical key (loader uses stem too).
                    meta_id = meta.get("id")
                    if meta_id:
                        world_id = world_id  # keep stem for routing
            except Exception:
                pass
            out.append(
                {
                    "world_id": world_id,
                    "name": name,
                    "version": version,
                    "description": description,
                    "yaml_path": str(yaml_file),
                }
            )
        except OSError:
            continue
    return out


def _demo_world_state(world_id: str) -> Dict[str, Any]:
    """
    Build the same shape as DB-mode /state for demo mode, sourced from YAML.
    """
    data = _load_yaml_world(world_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"World {world_id} not found")

    world_meta = data.get("world_meta", {}) or {}
    parameters = data.get("world_parameters", []) or []
    locations = data.get("locations", []) or []
    npcs = data.get("npcs", []) or []
    items = data.get("items", []) or []

    # Use the loaded lore loader's metadata to surface parse status
    loader_meta = world_lore_loader.get_metadata(world_id)
    is_parsed = bool(loader_meta and loader_meta.is_parsed)

    return {
        "world_id": world_id,
        "loaded": True,
        "world_meta": world_meta,
        "parameters": [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "category": p.get("category"),
                "current_level": p.get("current_level", 0),
            }
            for p in parameters
        ],
        "locations_count": len(locations),
        "npcs_count": len(npcs),
        "items_count": len(items),
        "is_parsed": is_parsed,
        "mode": "demo",
    }


def _demo_world_parameters(world_id: str) -> Dict[str, Any]:
    """Return the `world_parameters` list from YAML, with current_level defaults."""
    data = _load_yaml_world(world_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"World {world_id} not found")

    world_meta = data.get("world_meta", {}) or {}
    parameters = data.get("world_parameters", []) or []

    return {
        "world_id": world_id,
        "name": world_meta.get("name", world_id),
        "version": world_meta.get("version", "unknown"),
        "parameters": parameters,
        "mode": "demo",
    }


def _demo_etl(world_id: str) -> Dict[str, Any]:
    """Stub ETL trigger for demo mode (no real work, just acknowledge)."""
    return {
        "world_id": world_id,
        "status": "queued",
        "mode": "demo",
        "message": "Demo mode: ETL is a no-op. Use DB mode to trigger real ETL.",
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }


# ============================================
# Routes
# ============================================

@router.get("/")
async def list_worlds() -> Dict[str, Any]:
    """List all available worlds (demo mode: from `worlds/`, DB mode: from PostgreSQL)."""
    if is_demo_mode():
        return {"worlds": _demo_list_worlds(), "mode": "demo"}

    # DB mode — original v3.6 behavior
    from ..db import get_db_session
    from ..models import World
    from sqlalchemy import select

    async with get_db_session() as session:
        result = await session.execute(
            select(World).where(World.is_active == True)
        )
        worlds = result.scalars().all()
        return {
            "worlds": [
                {
                    "world_id": w.id,
                    "name": w.name,
                    "version": w.version,
                }
                for w in worlds
            ],
            "mode": "db",
        }


@router.get("/{world_id}/state")
async def get_world_state(world_id: str) -> Dict[str, Any]:
    """Get current world state (parameters, events, etc.)."""
    if is_demo_mode():
        return _demo_world_state(world_id)

    # DB mode — original v3.6 behavior
    from ..db import get_db_session
    from ..models import World, WorldParameterState
    from sqlalchemy import select

    async with get_db_session() as session:
        world = await session.get(World, world_id)
        if not world:
            raise HTTPException(status_code=404, detail=f"World {world_id} not found")

        result = await session.execute(
            select(WorldParameterState).where(WorldParameterState.world_id == world_id)
        )
        params = result.scalars().all()

        return {
            "world_id": world.id,
            "name": world.name,
            "version": world.version,
            "parameters": [
                {
                    "id": p.parameter_id,
                    "current_level": p.current_level,
                    "last_change_at": p.last_change_at.isoformat() if p.last_change_at else None,
                }
                for p in params
            ],
            "mode": "db",
        }


@router.get("/{world_id}/parameters")
async def get_world_parameters(world_id: str) -> Dict[str, Any]:
    """Get all world parameters and their current levels."""
    if is_demo_mode():
        return _demo_world_parameters(world_id)
    # DB mode delegates to the same backing logic as /state
    return await get_world_state(world_id)


@router.post("/{world_id}/etl")
async def trigger_daily_etl(world_id: str) -> Dict[str, Any]:
    """Manually trigger daily ETL (admin only)."""
    if is_demo_mode():
        return _demo_etl(world_id)
    return {
        "world_id": world_id,
        "message": "TODO: Implement ETL trigger (calls God Agent)",
        "mode": "db",
    }
