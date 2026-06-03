"""
WebSocket package.

Modules:
- game_socket: FastAPI WebSocket endpoint
- connection_manager: Registry of active connections
- action_queue: In-memory queue for player actions
- llm_worker: Background task that calls LLM

Architecture:
  Client (WS) → game_socket → ActionQueue → LLMWorker (background)
                                                    ↓
                                              PostgreSQL
                                                    ↓
                                              Broadcaster (via registry)
                                                    ↓
                                              Client (WS)

Key invariant: WS Handler NEVER awaits LLM directly.
"""
from .connection_manager import registry as connection_registry, ConnectionRegistry
from .action_queue import action_queue as queue_instance, ActionQueue
from .llm_worker import llm_worker as worker_instance, LLMWorker, init_worker
from .game_socket import websocket_endpoint

__all__ = [
    "connection_registry",
    "ConnectionRegistry",
    "action_queue",
    "ActionQueue",
    "llm_worker",
    "LLMWorker",
    "init_worker",
    "websocket_endpoint",
]
