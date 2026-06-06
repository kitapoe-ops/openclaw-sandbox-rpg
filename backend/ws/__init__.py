"""
WebSocket package (v3.0 -- simplified).

Modules:
- game_socket: FastAPI WebSocket endpoint
- connection_manager: Active connection tracking
- scene_locks: Per-scene async lock for LLM call serialization

Architecture (1-4 player single-host):
  Client (WS) -> game_socket -> asyncio.create_task -> scene_lock -> LLM -> DB -> broadcast

Key simplifications from v2.0:
- No separate ActionQueue class (use asyncio.create_task)
- No separate LLMWorker (BackgroundTasks inline)
- No in-memory pending updates (DB-driven recovery)
- Per-scene lock instead of per-character (allows parallel scenes)
"""
from .connection_manager import ConnectionRegistry, registry
from .game_socket import websocket_endpoint
from .scene_locks import SceneLockManager, scene_lock_manager

__all__ = [
    "registry",
    "ConnectionRegistry",
    "scene_lock_manager",
    "SceneLockManager",
    "websocket_endpoint",
]
