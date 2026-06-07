"""
Scene API Endpoints (v3.7 — demo + DB modes)
"""
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import func

from ..demo_mode import is_demo_mode
from ..scenes_demo import DEMO_SCENE, get_demo_scene

logger = logging.getLogger(__name__)

router = APIRouter()


def _current_round_from_db(character_id: str) -> int:
    """Look up the next round for this character.

    Returns the count of action_history rows + 1. We use COUNT
    rather than MAX(round_number) because the round_number
    column has historically been unreliable (0/1 oscillation
    when M3 returns null). COUNT gives a stable monotonic
    counter that always advances by 1 per submit.

    NOTE: this is a sync helper. Inside a FastAPI async endpoint
    we can't call asyncio.run() because there's a running loop.
    The endpoint (get_current_scene below) runs the query
    directly via an async helper and passes the result.
    """
    return 1  # placeholder; endpoint uses _current_round_from_db_async instead


async def _current_round_from_db_async(character_id: str) -> int:
    """Async version of _current_round_from_db. Called from
    inside the running event loop."""
    try:
        from ..db import engine
        from sqlalchemy import text as _sql_text
        async with engine.begin() as conn:
            r = await conn.execute(
                _sql_text(
                    "SELECT COUNT(*) FROM action_history WHERE character_id = :cid"
                ),
                {"cid": character_id},
            )
            count = r.scalar() or 0
            return int(count) + 1
    except Exception as e:
        logger.warning(f"Failed to query current round for {character_id}: {e}")
        return 1


@router.get("/{character_id}")
async def get_current_scene(character_id: str) -> dict[str, Any]:
    """
    Get the current scene for a character.
    Demo mode: returns hard-coded scene based on character.
    Full mode: queries DB for character.current_scene_id, then scene.
    """
    # Demo mode: just return demo scene
    if is_demo_mode():
        demo = get_demo_scene("loc_phandalin_town")
        if demo:
            return {
                "round": 1,
                "character_id": character_id,
                "scene_id": demo["scene_id"],
                "narrative": demo["scene_narrative"],
                "choices": demo["choices"],
                "state_changes": {},
                "minor_event": demo.get("minor_event"),
                "mode": "demo",
            }
        raise HTTPException(status_code=404, detail="Demo scene not found")

    # Full mode: query DB
    try:
        from ..db import get_db_session
        from ..models import CharacterState, Scene

        async with get_db_session() as session:
            char = await session.get(CharacterState, character_id)
            if not char:
                # Fallback to demo
                demo = get_demo_scene("loc_phandalin_town")
                if demo:
                    return _format_demo_response(character_id, demo)
                raise HTTPException(status_code=404, detail=f"Character {character_id} not found")

            scene = await session.get(Scene, char.current_scene_id)
            if not scene:
                raise HTTPException(
                    status_code=404, detail=f"Scene {char.current_scene_id} not found"
                )

            # Phase L2-E hotfix: round = max(prior round) + 1.
            # Previously hardcoded to 1, which meant the choice
            # card always showed 'Round 1' and never incremented.
            current_round = await _current_round_from_db_async(character_id)

            return {
                "round": current_round,
                "character_id": character_id,
                "scene_id": scene.id,
                "narrative": scene.description,
                "choices": DEMO_SCENE["choices"],  # TODO: persist scene choices
                "state_changes": {},
                "minor_event": None,
            }
    except Exception as e:
        # DB error — fall back to demo
        demo = get_demo_scene("loc_phandalin_town")
        if demo:
            return _format_demo_response(character_id, demo)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_id}/history")
async def get_scene_history(character_id: str, limit: int = 20) -> dict[str, Any]:
    """Get last N scenes for the character."""
    return {
        "character_id": character_id,
        "limit": limit,
        "history": [],
        "mode": "demo" if is_demo_mode() else "full",
    }


def _format_demo_response(character_id: str, scene: dict[str, Any]) -> dict[str, Any]:
    return {
        "round": 1,
        "character_id": character_id,
        "scene_id": scene["scene_id"],
        "narrative": scene["scene_narrative"],
        "choices": scene["choices"],
        "state_changes": {},
        "minor_event": scene.get("minor_event"),
        "mode": "demo",
    }
