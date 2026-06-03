"""
Main FastAPI Application (v3.7 — DEMO MODE support)
=====================================================
Can run with ZERO infrastructure:
  DEMO_MODE=true uvicorn backend.main:app

Or with full DB:
  docker-compose up -d
  uvicorn backend.main:app

Auto-detect:
  DEMO_MODE=auto (default) — tries DB, falls back to demo
"""
import os
import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .api import character, action, scene, world
from .ws import websocket_endpoint, registry, scene_lock_manager
from .demo_mode import is_demo_mode
from .scenes_demo import DEMO_SCENE, DEMO_STARTER

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================
# Lifespan
# ============================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("OpenClaw Sandbox RPG — Starting (v3.7)")
    logger.info("=" * 60)

    # Detect mode
    demo = is_demo_mode()
    if demo:
        logger.info("[Mode] DEMO MODE — no DB required")
        logger.info(f"[Demo] Character: {DEMO_STARTER['character_id']}")
        logger.info(f"[Demo] Scene: {DEMO_SCENE['scene_id']}")
    else:
        logger.info("[Mode] FULL MODE — connecting to DB")
        try:
            from .db import init_db, get_db_session, engine
            from .models import World, Scene, CharacterState

            await init_db()
            logger.info("[Startup] DB schema initialized")

            # Seed demo data
            async with get_db_session() as session:
                # World
                world_obj = await session.get(World, DEMO_STARTER["world_id"])
                if not world_obj:
                    session.add(World(
                        id=DEMO_STARTER["world_id"],
                        name="被遺忘嘅國度 — 凡達林地區",
                        version="D&D_5e_SRD_v5.1.0",
                        config={"yaml_path": "worlds/dnd_5e_forgotten_realms.yaml"},
                        is_active=True,
                    ))
                # Scene
                scene_obj = await session.get(Scene, DEMO_SCENE["scene_id"])
                if not scene_obj:
                    session.add(Scene(
                        id=DEMO_SCENE["scene_id"],
                        world_id=DEMO_STARTER["world_id"],
                        name="凡達林鎮 (Phandalin Town)",
                        description=DEMO_SCENE["scene_narrative"],
                        location_tag="settlement",
                        environment_tags=["outdoor", "settlement", "town", "frontier"],
                        active_npcs=[
                            "npc_gundren", "npc_halia", "npc_sister_garaele",
                            "npc_redbrand_ringleader", "npc_injured_traveler_01",
                        ],
                        atmosphere="tense",
                        is_dynamic=False,
                    ))
                # Character
                char_obj = await session.get(CharacterState, DEMO_STARTER["character_id"])
                if not char_obj:
                    session.add(CharacterState(
                        character_id=DEMO_STARTER["character_id"],
                        name=DEMO_STARTER["name"],
                        world_id=DEMO_STARTER["world_id"],
                        current_scene_id=DEMO_STARTER["current_scene_id"],
                        semantic_profile=DEMO_STARTER["semantic_profile"],
                        is_npc_mode=False,
                        is_alive=True,
                    ))
            logger.info("[Startup] Demo data seeded")

            # Recover zombies
            try:
                from sqlalchemy import text
                async with get_db_session() as session:
                    result = await session.execute(text("SELECT recover_interrupted_actions()"))
                    recovered = result.scalar() or 0
                    if recovered > 0:
                        logger.warning(f"[Startup] Recovered {recovered} zombie actions")
            except Exception as e:
                logger.debug(f"[Startup] Zombie recovery skipped: {e}")

            await engine.dispose()
        except Exception as e:
            logger.exception(f"[Startup] DB init failed: {e}")

    logger.info("=" * 60)
    logger.info("[Startup] Ready. Try: curl http://localhost:8000/health")
    logger.info("=" * 60)

    yield

    logger.info("[Shutdown] Cleanup...")


# ============================================
# App
# ============================================
app = FastAPI(
    title="OpenClaw Sandbox RPG",
    version="0.4.0",
    description="Async multiplayer semantic-state-machine sandbox RPG",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API
app.include_router(character.router, prefix="/api/character", tags=["character"])
app.include_router(action.router, prefix="/api/action", tags=["action"])
app.include_router(scene.router, prefix="/api/scene", tags=["scene"])
app.include_router(world.router, prefix="/api/world", tags=["world"])

# WebSocket
@app.websocket("/ws/game/{character_id}")
async def ws_game(websocket: WebSocket, character_id: str):
    await websocket_endpoint(websocket, character_id)


# ============================================
# Health + Root + Demo helper
# ============================================
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "0.4.0",
        "mode": "demo" if is_demo_mode() else "full",
        "registry": registry.stats(),
        "scene_locks": scene_lock_manager.stats(),
    }


@app.get("/")
async def root():
    return {
        "name": "OpenClaw Sandbox RPG",
        "version": "0.4.0",
        "docs": "/docs",
        "demo": {
            "character_id": DEMO_STARTER["character_id"],
            "scene_id": DEMO_SCENE["scene_id"],
            "character_url": f"/api/character/{DEMO_STARTER['character_id']}",
            "scene_url": f"/api/scene/{DEMO_STARTER['character_id']}",
            "ws_url": f"/ws/game/{DEMO_STARTER['character_id']}",
        },
    }
