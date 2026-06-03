"""
WebSocket Endpoint (v3.1 — security hardened)
==============================================
Changes from v3.0:
- scene_id is NO LONGER trusted from client payload
- Server reads current_scene_id from character_states table (SOURCE OF TRUTH)
- Mismatch between client claim and DB state = REJECTED with state_mismatch error
- Database session injected for state lookups
- All PENDING/PROCESSING tasks must be INTERRUPTED on FastAPI startup (zombie recovery)

Architecture:
  Client (WS) -> game_socket -> DB read scene_id -> asyncio.create_task ->
  scene_lock -> LLM -> DB write -> broadcast
"""
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from .connection_manager import registry
from .scene_locks import scene_lock_manager
from ..db import get_db_session  # Will be implemented

logger = logging.getLogger(__name__)


async def websocket_endpoint(
    websocket: WebSocket,
    character_id: str,
):
    """
    WebSocket endpoint for a specific character.

    CRITICAL: scene_id is NEVER read from client payload.
    Always queried from DB character_states.current_scene_id.
    """
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
            "message": "Connected. Server controls scene_id. Call GET /api/scene/{character_id} for latest state.",
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
                # Validate and dispatch — scene_id is read from DB, not client
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
    """
    Background task: process a player action.

    SECURITY: scene_id is read from DB, not from client payload.
    Mismatch between client claim and DB state triggers state_mismatch error.
    """
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

    # === SECURITY CHECK: scene_id is DB-controlled ===
    # Read current_scene_id from character_states (SOURCE OF TRUTH)
    db_session = get_db_session()
    try:
        character_state = await db_session.get_character_state(character_id)
        if not character_state:
            await _send_or_broadcast(websocket, character_id, {
                "type": "error",
                "code": "character_not_found",
                "task_id": task_id,
                "message": f"Character {character_id} does not exist",
            })
            return

        if not character_state.get("is_alive", True):
            await _send_or_broadcast(websocket, character_id, {
                "type": "error",
                "code": "character_dead",
                "task_id": task_id,
                "message": "Character is dead. Use soul transfer to continue.",
            })
            return

        # The authoritative scene_id from DB
        authoritative_scene_id = character_state["current_scene_id"]

        # Optional: check client's claimed scene_id for mismatch
        # This is a defense against replay attacks or client bugs
        client_claimed_scene_id = msg.get("scene_id")
        if client_claimed_scene_id and client_claimed_scene_id != authoritative_scene_id:
            logger.warning(
                f"[Security] scene_id mismatch for {character_id}: "
                f"client={client_claimed_scene_id}, server={authoritative_scene_id}"
            )
            await _send_or_broadcast(websocket, character_id, {
                "type": "error",
                "code": "state_mismatch",
                "task_id": task_id,
                "message": "Client scene_id does not match server. Refresh state.",
                "client_scene_id": client_claimed_scene_id,
                "server_scene_id": authoritative_scene_id,
            })
            return  # REJECT — do not process

        # Use the DB-authoritative scene_id
        scene_id = authoritative_scene_id

    finally:
        await db_session.close()

    # === Insert PENDING row into action_history ===
    action_id = await db_session.create_action_history(
        character_id=character_id,
        scene_id=scene_id,
        round_number=msg.get("round", 0),
        player_choice=msg.get("choice") or msg.get("player_input"),
        execution_status="PENDING",
    )

    # === Send action_accepted immediately ===
    try:
        await websocket.send_json({
            "type": "action_accepted",
            "task_id": task_id,
            "action_id": action_id,
            "character_id": character_id,
            "scene_id": scene_id,  # Echo back the authoritative scene_id
            "status": "processing",
            "message": "Action accepted, generating scene...",
        })
    except Exception:
        # WS may be closed; that's OK, result will be persisted to DB
        pass

    # === Mark as PROCESSING ===
    await db_session.update_action_history(
        action_id,
        execution_status="PROCESSING",
        started_at=datetime.utcnow(),
    )

    try:
        # Acquire per-scene lock (NOT per-character — Q2 gray area decision)
        lock = await scene_lock_manager.get_lock(scene_id)
        async with lock:
            logger.info(f"[Task {task_id}] Acquired lock for scene {scene_id}")
            scene_output = await _call_llm(character_id, scene_id, msg)

            # Persist COMPLETED status
            await db_session.update_action_history(
                action_id,
                execution_status="COMPLETED",
                completed_at=datetime.utcnow(),
                llm_narrative_output=scene_output.get("narrative"),
                llm_choices_output=scene_output.get("choices"),
                llm_state_changes=scene_output.get("state_changes"),
            )

            # Update character state if needed
            if scene_output.get("state_changes"):
                await db_session.apply_state_changes(character_id, scene_output["state_changes"])

            # Update current_scene_id if scene changed
            if scene_output.get("new_scene_id"):
                await db_session.update_character_scene(character_id, scene_output["new_scene_id"])

            logger.info(f"[Task {task_id}] LLM complete, broadcasting")

        # Broadcast OUTSIDE the lock
        await registry.broadcast(character_id, {
            "type": "scene_update",
            "task_id": task_id,
            "action_id": action_id,
            "round": scene_output.get("round"),
            "scene_id": scene_id,
            "narrative": scene_output.get("narrative"),
            "choices": scene_output.get("choices"),
            "state_changes": scene_output.get("state_changes"),
            "minor_event": scene_output.get("minor_event"),
            "timestamp": datetime.utcnow().isoformat(),
        })

    except Exception as e:
        logger.exception(f"[Task {task_id}] Failed: {e}")
        # Mark as FAILED
        try:
            await db_session.update_action_history(
                action_id,
                execution_status="FAILED",
                completed_at=datetime.utcnow(),
                error_message=str(e),
            )
        except Exception:
            pass
        try:
            await registry.broadcast(character_id, {
                "type": "task_status",
                "task_id": task_id,
                "action_id": action_id,
                "status": "failed",
                "error": str(e),
            })
        except Exception:
            pass


async def _send_or_broadcast(websocket: WebSocket, character_id: str, message: dict):
    """Try to send via WS, fall back to broadcast (which silently drops if no connection)."""
    try:
        await websocket.send_json(message)
    except Exception:
        await registry.broadcast(character_id, message)


async def _call_llm(character_id: str, scene_id: str, player_input: dict) -> dict:
    """
    Call Scene Agent + Sub Agent to generate scene output.

    TODO: Implement actual LLM integration.
    Reference: docs/PROMPTS/scene_agent_prompt.md
    """
    logger.info(f"[LLM] Generating scene for {character_id} in {scene_id}")
    await asyncio.sleep(2)
    return {
        "round": 1,
        "scene_id": scene_id,
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
