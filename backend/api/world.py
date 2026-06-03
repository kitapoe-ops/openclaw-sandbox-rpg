"""
World API Endpoints (v3.6)
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any

from ..db import get_db_session
from ..models import World, WorldParameterState, WorldEvent
from sqlalchemy import select

router = APIRouter()


@router.get("/")
async def list_worlds() -> Dict[str, Any]:
    """List all available worlds."""
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
            ]
        }


@router.get("/{world_id}/state")
async def get_world_state(world_id: str) -> Dict[str, Any]:
    """Get current world state (parameters, events, etc.)."""
    async with get_db_session() as session:
        world = await session.get(World, world_id)
        if not world:
            raise HTTPException(status_code=404, detail=f"World {world_id} not found")

        # Get parameter states
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
        }


@router.get("/{world_id}/parameters")
async def get_world_parameters(world_id: str) -> Dict[str, Any]:
    """Get all world parameters and their current levels."""
    return await get_world_state(world_id)


@router.post("/{world_id}/etl")
async def trigger_daily_etl(world_id: str) -> Dict[str, Any]:
    """Manually trigger daily ETL (admin only)."""
    return {
        "world_id": world_id,
        "message": "TODO: Implement ETL trigger (calls God Agent)",
    }
