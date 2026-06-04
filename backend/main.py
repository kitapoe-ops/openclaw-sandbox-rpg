"""
Main FastAPI application entry point.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from .api import character, action, scene, world
from .ws import game_socket
from .config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting OpenClaw Sandbox RPG backend...")
    # TODO: Initialize database, LLM clients, world loaders
    yield
    # Shutdown
    logger.info("Shutting down...")


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

# WebSocket
app.add_api_websocket_route("/ws/game/{character_id}", game_socket.websocket_endpoint)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "0.1.0"}


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "OpenClaw Sandbox RPG API",
        "version": "0.1.0",
        "docs": "/docs",
    }
