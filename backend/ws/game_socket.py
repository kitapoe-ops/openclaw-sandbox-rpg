"""
WebSocket Connection Manager (Revised v2.0)
=============================================
Decouples LLM task lifetime from WebSocket lifetime.

Architecture:
  Client (WS) → ActionQueue (in-memory) → LLM Worker (background)
                                                    ↓
                                              PostgreSQL (persistent)
                                                    ↓
                                              Broadcaster polls WS Registry
                                                    ↓
                                              Client (WS) ← scene_update

Key principles:
1. WS Handler NEVER awaits LLM directly
2. LLM tasks are fire-and-forget with task_id returned
3. State changes are persisted to DB, not just to socket
4. Broadcaster queries DB for pending updates per character_id
5. Reconnection is handled by re-subscribing, not by re-processing tasks

Reference: backend/ws/connection_manager.py
           backend/ws/broadcaster.py
           backend/ws/action_queue.py
"""
from fastapi import WebSocket, WebSocketDisconnect, status
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Optional

from .connection_manager import ConnectionRegistry
from .action_queue import ActionQueue, QueuedAction

logger = logging.getLogger(__name__)


async def websocket_endpoint(
    websocket: WebSocket,
    character_id: str,
    registry: ConnectionRegistry,
    action_queue: ActionQueue,
):
    """
    WebSocket endpoint for a specific character.

    Lifecycle:
    1. Accept connection
    2. Register in ConnectionRegistry
    3. Send connection_ack with any pending updates from DB
    4. Loop: receive → validate → enqueue (non-blocking) → continue
    5. On disconnect: unregister (but tasks continue)

    CRITICAL: This function MUST NEVER call LLM directly.
    It only enqueues work; the LLM Worker processes it in background.
    """
    await websocket.accept()
    connection_id = str(uuid.uuid4())
    logger.info(f"[WS {connection_id}] Connecting for character: {character_id}")

    try:
        # 1. Register the connection
        await registry.register(character_id, connection_id, websocket)

        # 2. Send connection acknowledgment
        await websocket.send_json({
            "type": "connection_ack",
            "connection_id": connection_id,
            "character_id": character_id,
            "timestamp": datetime.utcnow().isoformat(),
        })

        # 3. Send any pending updates (e.g., from tasks that completed while disconnected)
        pending = await registry.get_pending_updates(character_id)
        for update in pending:
            await websocket.send_json(update)
        await registry.clear_pending_updates(character_id)

        # 4. Main receive loop — non-blocking
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "code": "invalid_json",
                    "message": "Message must be valid JSON",
                })
                continue

            msg_type = msg.get("type")

            # Ping/Pong — keep connection alive
            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "ts": datetime.utcnow().isoformat()})
                continue

            # Action submission — ENQUEUE, do not process
            if msg_type == "action_submit":
                await _enqueue_action(websocket, character_id, msg, action_queue)
                continue

            # Unknown message type
            await websocket.send_json({
                "type": "error",
                "code": "unknown_message_type",
                "message": f"Unknown message type: {msg_type}",
            })

    except WebSocketDisconnect:
        logger.info(f"[WS {connection_id}] Client disconnected")
    except Exception as e:
        logger.exception(f"[WS {connection_id}] Unexpected error: {e}")
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass
    finally:
        # CRITICAL: Unregister but do NOT cancel any running LLM tasks
        # Tasks continue; their results will be persisted to DB
        # and sent when client reconnects
        await registry.unregister(character_id, connection_id)
        logger.info(f"[WS {connection_id}] Cleaned up")


async def _enqueue_action(
    websocket: WebSocket,
    character_id: str,
    msg: dict,
    action_queue: ActionQueue,
):
    """
    Enqueue a player action for background processing.

    This function does NOT call LLM. It:
    1. Validates basic structure
    2. Generates a task_id
    3. Pushes to ActionQueue
    4. Sends immediate acknowledgment to client
    5. Returns immediately (non-blocking)
    """
    try:
        # Basic validation
        if "player_input" not in msg and "choice" not in msg:
            await websocket.send_json({
                "type": "error",
                "code": "invalid_action",
                "message": "Missing player_input or choice",
            })
            return

        task_id = str(uuid.uuid4())
        action = QueuedAction(
            task_id=task_id,
            character_id=character_id,
            payload=msg,
            submitted_at=datetime.utcnow(),
        )
        await action_queue.enqueue(action)

        # Immediate acknowledgment — client can show "processing..."
        await websocket.send_json({
            "type": "action_accepted",
            "task_id": task_id,
            "character_id": character_id,
            "status": "processing",
            "message": "Action queued for processing",
        })

        logger.info(f"[WS] Enqueued task {task_id} for character {character_id}")

    except Exception as e:
        logger.exception(f"[WS] Failed to enqueue action: {e}")
        await websocket.send_json({
            "type": "error",
            "code": "enqueue_failed",
            "message": "Failed to enqueue action",
        })
