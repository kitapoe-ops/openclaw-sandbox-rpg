"""
Main FastAPI application entry point.
"""
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from .api import character, action, scene, world
from .ws import (
    websocket_endpoint,
    connection_registry,
    action_queue,
    init_worker,
)
from .config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting OpenClaw Sandbox RPG backend...")

    # Initialize the LLM worker (background task)
    worker = init_worker(action_queue, connection_registry)
    await worker.start()
    logger.info("LLM Worker started")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await worker.stop()
    logger.info("LLM Worker stopped")


app = FastAPI(
    title="OpenClaw Sandbox RPG",
    version="0.1.0",
    description="Async multiplayer semantic-state-machine sandbox RPG",
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


# WebSocket endpoint — wires endpoint function to dependencies via closure
@app.websocket("/ws/game/{character_id}")
async def ws_game(websocket: WebSocket, character_id: str):
    await websocket_endpoint(
        websocket=websocket,
        character_id=character_id,
        registry=connection_registry,
        action_queue=action_queue,
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "registry": connection_registry.stats(),
        "queue": action_queue.stats(),
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "OpenClaw Sandbox RPG API",
        "version": "0.1.0",
        "docs": "/docs",
    }
