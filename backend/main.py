"""
Main FastAPI Application (v3.6 — production-ready skeleton)
==============================================================
Startup:
  1. Recover zombie PENDING/PROCESSING actions (Q6 safety)
  2. Init DB schema (create tables if not exist)
  3. Seed demo data (D&D 5e starter + scene)
  4. Start LLM worker pool (when implemented)

Features:
  - REST API for character/scene/world
  - WebSocket for real-time game events
  - Health check with system stats
"""
import os
import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .api import character, action, scene, world
from .ws import websocket_endpoint, registry, scene_lock_manager
from .db import engine, init_db, get_db_session
from .models import World, Scene, CharacterState
from .scenes_demo import DEMO_SCENE, DEMO_STARTER

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================
# Seed data on startup
# ============================================
async def seed_demo_data():
    """Insert D&D 5e world + Phandalin scene + demo character if not exist."""
    async with get_db_session() as session:
        # World
        world = await session.get(World, DEMO_STARTER["world_id"])
        if not world:
            session.add(World(
                id=DEMO_STARTER["world_id"],
                name="被遺忘嘅國度 — 凡達林地區",
                version="D&D_5e_SRD_v5.1.0",
                config={"yaml_path": "worlds/dnd_5e_forgotten_realms.yaml"},
                is_active=True,
            ))
            logger.info(f"Seeded world: {DEMO_STARTER['world_id']}")

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
            logger.info(f"Seeded scene: {DEMO_SCENE['scene_id']}")

        # Character
        char = await session.get(CharacterState, DEMO_STARTER["character_id"])
        if not char:
            session.add(CharacterState(
                character_id=DEMO_STARTER["character_id"],
                name=DEMO_STARTER["name"],
                world_id=DEMO_STARTER["world_id"],
                current_scene_id=DEMO_STARTER["current_scene_id"],
                semantic_profile=DEMO_STARTER["semantic_profile"],
                is_npc_mode=False,
                is_alive=True,
            ))
            logger.info(f"Seeded character: {DEMO_STARTER['character_id']}")


# ============================================
# Lifespan
# ============================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("OpenClaw Sandbox RPG — Starting (v3.6)")
    logger.info("=" * 60)

    # 1. Init DB schema
    try:
        await init_db()
        logger.info("[Startup] DB schema initialized")
    except Exception as e:
        logger.exception(f"[Startup] DB init failed (will use demo data): {e}")

    # 2. Seed demo data
    try:
        await seed_demo_data()
        logger.info("[Startup] Demo data seeded")
    except Exception as e:
        logger.exception(f"[Startup] Demo seed failed: {e}")

    # 3. Recover zombie actions
    try:
        from sqlalchemy import text
        async with get_db_session() as session:
            result = await session.execute(
                text("SELECT recover_interrupted_actions()")
            )
            recovered = result.scalar() or 0
            if recovered > 0:
                logger.warning(f"[Startup] Recovered {recovered} zombie actions")
    except Exception as e:
        logger.debug(f"[Startup] Zombie recovery skipped (function not in DB yet): {e}")

    logger.info("[Startup] Ready")
    yield
    logger.info("[Shutdown] Cleanup...")
    await engine.dispose()


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
# Health + Root
# ============================================
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "0.4.0",
        "registry": registry.stats(),
        "scene_locks": scene_lock_manager.stats(),
    }


@app.get("/")
async def root():
    return {
        "name": "OpenClaw Sandbox RPG",
        "version": "0.4.0",
        "docs": "/docs",
        "demo_character_id": DEMO_STARTER["character_id"],
        "demo_scene_id": DEMO_SCENE["scene_id"],
    }
