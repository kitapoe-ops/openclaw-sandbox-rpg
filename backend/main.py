"""
Main FastAPI application entry point (v3.1 — security hardened + zombie recovery).
"""
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from .api import character, action, scene, world
from .ws import (
    websocket_endpoint,
    registry,
    scene_lock_manager,
)
from .config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Startup:
    1. Recover any zombie PENDING/PROCESSING actions from previous run
    2. Mark them as INTERRUPTED so client can re-submit
    """
    logger.info("Starting OpenClaw Sandbox RPG backend (v3.1 — single-host, secure)...")

    # === ZOMBIE RECOVERY ===
    # Any actions left in PENDING/PROCESSING from a previous run are now zombies
    # (in-memory tasks died with the process). Mark them as INTERRUPTED.
    try:
        from .db import get_db_session
        session = get_db_session()
        recovered = await session.recover_interrupted_actions()
        if recovered > 0:
            logger.warning(
                f"[Startup] Recovered {recovered} zombie actions → marked INTERRUPTED"
            )
    except Exception as e:
        logger.exception(f"[Startup] Zombie recovery failed (DB may not be ready): {e}")

    yield

    logger.info("Shutting down...")
    logger.info(f"Final stats: registry={registry.stats()}, locks={scene_lock_manager.stats()}")


app = FastAPI(
    title="OpenClaw Sandbox RPG",
    version="0.3.0",
    description="Async multiplayer semantic-state-machine sandbox RPG (single-host, secure)",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API routes
app.include_router(character.router, prefix="/api/character", tags=["character"])
app.include_router(action.router, prefix="/api/action", tags=["action"])
app.include_router(scene.router, prefix="/api/scene", tags=["scene"])
app.include_router(world.router, prefix="/api/world", tags=["world"])


# WebSocket endpoint
@app.websocket("/ws/game/{character_id}")
async def ws_game(websocket: WebSocket, character_id: str):
    await websocket_endpoint(websocket, character_id)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "0.3.0",
        "registry": registry.stats(),
        "scene_locks": scene_lock_manager.stats(),
    }


@app.get("/")
async def root():
    return {
        "message": "OpenClaw Sandbox RPG API",
        "version": "0.3.0",
        "docs": "/docs",
    }
