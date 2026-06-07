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
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .api import action, character, scene, world
from .demo_mode import is_demo_mode
from .scenes_demo import DEMO_SCENE, DEMO_STARTER
from .ws import registry, scene_lock_manager, websocket_endpoint

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

    # Phase L2-B: production safety guard (2026-06-07)
    # When ENV=production, demo mode is FORBIDDEN. This prevents
    # silent fallback to in-memory demo data if DATABASE_URL is
    # misconfigured. Per user explicit decision (B): demo mode
    # remains an opt-in for development, but production MUST hit
    # the real DB or refuse to start (fail-loud).
    env = os.getenv("ENV", "development").lower()
    if env == "production" and demo:
        raise RuntimeError(
            "PRODUCTION SAFETY: ENV=production requires DATABASE_URL to be reachable. "
            "Demo mode is opt-in for development only. "
            "Set ENV=development to explicitly opt in, or fix your DB connection. "
            "(backend/demo_mode.py)"
        )
    logger.info(f"[Env] ENV={env}, mode={'demo' if demo else 'full'}")

    if demo:
        logger.info("[Mode] DEMO MODE — no DB required")
        logger.info(f"[Demo] Character: {DEMO_STARTER['character_id']}")
        logger.info(f"[Demo] Scene: {DEMO_SCENE['scene_id']}")
    else:
        logger.info("[Mode] FULL MODE — connecting to DB")
        try:
            from .db import engine, get_db_session, init_db
            from .models import CharacterState, Scene, World

            await init_db()
            logger.info("[Startup] DB schema initialized")

            # Seed demo data
            async with get_db_session() as session:
                # World
                world_obj = await session.get(World, DEMO_STARTER["world_id"])
                if not world_obj:
                    session.add(
                        World(
                            id=DEMO_STARTER["world_id"],
                            name="被遺忘嘅國度 — 凡達林地區",
                            version="D&D_5e_SRD_v5.1.0",
                            config={"yaml_path": "worlds/dnd_5e_forgotten_realms.yaml"},
                            is_active=True,
                        )
                    )
                # Scene
                scene_obj = await session.get(Scene, DEMO_SCENE["scene_id"])
                if not scene_obj:
                    session.add(
                        Scene(
                            id=DEMO_SCENE["scene_id"],
                            world_id=DEMO_STARTER["world_id"],
                            name="凡達林鎮 (Phandalin Town)",
                            description=DEMO_SCENE["scene_narrative"],
                            location_tag="settlement",
                            environment_tags=["outdoor", "settlement", "town", "frontier"],
                            active_npcs=[
                                "npc_gundren",
                                "npc_halia",
                                "npc_sister_garaele",
                                "npc_redbrand_ringleader",
                                "npc_injured_traveler_01",
                            ],
                            atmosphere="tense",
                            is_dynamic=False,
                        )
                    )
                # Character
                char_obj = await session.get(CharacterState, DEMO_STARTER["character_id"])
                if not char_obj:
                    session.add(
                        CharacterState(
                            character_id=DEMO_STARTER["character_id"],
                            name=DEMO_STARTER["name"],
                            world_id=DEMO_STARTER["world_id"],
                            current_scene_id=DEMO_STARTER["current_scene_id"],
                            semantic_profile=DEMO_STARTER["semantic_profile"],
                            is_npc_mode=False,
                            is_alive=True,
                        )
                    )
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

# Phase L2-E hotfix: disable ALL caching for HTML and JS bundle
# responses. Telegram's in-app browser, mobile Safari, and many
# Android browsers cache aggressively even on hard reload,
# and the user has reported the same 'blank/hung' bug 7 times
# in a row despite the Python e2e test passing every time. The
# most likely cause is the browser pinning an OLD bundle. By
# adding no-cache headers we force every load to hit Cloudflare
# and the backend, which in turn means the next commit's new
# bundle hash will be picked up on the very next reload.
@app.middleware("http")
async def _no_cache_middleware(request, call_next):
    response = await call_next(request)
    # Only add no-cache to HTML and JS/CSS assets (not the JSON
    # API — that one can stay cacheable for short bursts).
    path = request.url.path
    if path == "/" or path.endswith(".html") or "/assets/" in path:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.add_middleware(
    CORSMiddleware,
    # Restrictive default; override via CORS_ORIGINS env var (comma-separated)
    # Wildcard origins are incompatible with allow_credentials=True per CORS spec,
    # so we ship a localhost-only default and let operators widen explicitly.
    allow_origins=os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
    ).split(","),
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


@app.get("/api")
async def api_info():
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


# ============================================
# Phase L2-G: Serve frontend SPA from frontend/dist/
# (Vue 3 + Vite build) at / and any non-/api path.
# This MUST come AFTER all API routes so they take precedence.
# ============================================
import pathlib
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_FRONTEND_DIST = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "dist"
_FRONTEND_DIST = _FRONTEND_DIST.resolve()
_FRONTEND_INDEX = _FRONTEND_DIST / "index.html"

if _FRONTEND_DIST.exists() and _FRONTEND_INDEX.exists():
    # Mount /assets (Vite outputs JS/CSS here)
    _assets_dir = _FRONTEND_DIST / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    @app.get("/")
    async def spa_root():
        return FileResponse(str(_FRONTEND_INDEX))

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # Don't shadow /api or /docs or /ws or /health
        if full_path.startswith(("api/", "docs", "redoc", "openapi.json", "ws/", "health")):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not Found")
        # Try to serve a static file first (e.g. /favicon.ico)
        candidate = _FRONTEND_DIST / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        # Otherwise SPA fallback to index.html (Vue Router history mode)
        return FileResponse(str(_FRONTEND_INDEX))
else:
    # No frontend dist — fall back to the JSON / endpoint
    @app.get("/")
    async def root():
        return {
            "name": "OpenClaw Sandbox RPG",
            "version": "0.4.0",
            "docs": "/docs",
            "frontend_dist_missing": True,
            "message": "frontend/dist/ not found. Run 'cd frontend && npm run build'.",
            "demo": {
                "character_id": DEMO_STARTER["character_id"],
                "scene_id": DEMO_SCENE["scene_id"],
                "character_url": f"/api/character/{DEMO_STARTER['character_id']}",
                "scene_url": f"/api/scene/{DEMO_STARTER['character_id']}",
                "ws_url": f"/ws/game/{DEMO_STARTER['character_id']}",
            },
        }
