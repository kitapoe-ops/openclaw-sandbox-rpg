"""
WebSocket Endpoint (Simplified v3.0)
======================================
Final architecture for 1-4 player single-host deployment:
  - FastAPI BackgroundTasks (no separate worker process)
  - Per-scene async locks (serialize NPC-interacting actions)
  - DB-driven state recovery (no in-memory pending updates)
  - Reconnect = query DB for latest scene, then "reclaim control"

Flow:
  Client connects
    -> Server sends connection_ack
    -> Client queries /api/scene/{id} via REST for latest state
    -> (Optional) Client sends "reclaim" message to mark as player-controlled

  Client sends action_submit
    -> Server validates, enqueues to asyncio.create_task
    -> Server sends action_accepted with task_id
    -> Background task: lock scene -> call LLM -> write DB -> broadcast
    -> Client receives scene_update
"""
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
import json
import logging
import uuid
from datetime import datetime

from .connection_manager import registry
from .scene_locks import scene_lock_manager

logger = logging.getLogger(__name__)


async def websocket_endpoint(
    websocket: WebSocket,
    character_id: str,
):
    await websocket.accept()
    connection_id = str(uuid.uuid4())
    logger.info(f"[WS {connection_id}] Connecting for character: {character_id}")

    try:
        await registry.register(character_id, connection_id, websocket)
        await websocket.send_json({
            "type": "connection_ack",
            "connection_id": connection_id,
            "character_id": character_id,
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Connected. Call GET /api/scene/{character_id} for latest state.",
        })

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

            if msg_type == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "ts": datetime.utcnow().isoformat(),
                })
                continue

            if msg_type == "action_submit":
                asyncio.create_task(
                    _process_action(websocket, character_id, msg, connection_id)
                )
                continue

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
            await websocket.close()
        except Exception:
            pass
    finally:
        await registry.unregister(character_id, connection_id)
        logger.info(f"[WS {connection_id}] Cleaned up")


async def _process_action(
    websocket: WebSocket,
    character_id: str,
    msg: dict,
    connection_id: str,
):
    task_id = str(uuid.uuid4())

    if "choice" not in msg and "player_input" not in msg:
        try:
            await websocket.send_json({
                "type": "error",
                "code": "invalid_action",
                "task_id": task_id,
                "message": "Missing choice or player_input",
            })
        except Exception:
            pass
        return

    try:
        await websocket.send_json({
            "type": "action_accepted",
            "task_id": task_id,
            "character_id": character_id,
            "status": "processing",
            "message": "Action accepted, generating scene...",
        })
    except Exception:
        pass

    scene_id = msg.get("scene_id", character_id)

    try:
        lock = await scene_lock_manager.get_lock(scene_id)
        async with lock:
            logger.info(f"[Task {task_id}] Acquired lock for scene {scene_id}")
            scene_output = await _call_llm(character_id, msg)
            logger.info(f"[Task {task_id}] LLM complete, broadcasting")

        await registry.broadcast(character_id, {
            "type": "scene_update",
            "task_id": task_id,
            "round": scene_output.get("round"),
            "narrative": scene_output.get("narrative"),
            "choices": scene_output.get("choices"),
            "state_changes": scene_output.get("state_changes"),
            "minor_event": scene_output.get("minor_event"),
            "timestamp": datetime.utcnow().isoformat(),
        })

    except Exception as e:
        logger.exception(f"[Task {task_id}] Failed: {e}")
        try:
            await registry.broadcast(character_id, {
                "type": "task_status",
                "task_id": task_id,
                "status": "failed",
                "error": str(e),
            })
        except Exception:
            pass


async def _call_llm(character_id: str, player_input: dict) -> dict:
    logger.info(f"[LLM] Generating scene for {character_id}")
    await asyncio.sleep(2)
    return {
        "round": 1,
        "narrative": "你睇到一個場景... (TODO: real LLM)",
        "choices": [
            {
                "id": "opt_01",
                "lore_source": "item:dummy",
                "text": "[行动] 继续探索",
                "intent_category": "environment",
                "attitude_options": [
                    {"dimension": "caution", "level": "careful"}
                ]
            }
        ],
        "state_changes": {},
        "minor_event": None,
    }
