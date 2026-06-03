"""
Main FastAPI application entry point (v3.0 -- simplified).
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
    """Application lifespan manager."""
    logger.info("Starting OpenClaw Sandbox RPG backend (v3.0 -- single-host)...")
    yield
    logger.info("Shutting down...")
    logger.info(f"Final stats: registry={registry.stats()}, locks={scene_lock_manager.stats()}")


app = FastAPI(
    title="OpenClaw Sandbox RPG",
    version="0.2.0",
    description="Async multiplayer semantic-state-machine sandbox RPG (single-host)",
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
        "version": "0.2.0",
        "registry": registry.stats(),
        "scene_locks": scene_lock_manager.stats(),
    }


@app.get("/")
async def root():
    return {
        "message": "OpenClaw Sandbox RPG API",
        "version": "0.2.0",
        "docs": "/docs",
    }
