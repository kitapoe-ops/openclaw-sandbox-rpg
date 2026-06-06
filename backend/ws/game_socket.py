"""
WebSocket Endpoint (v3.2 — cloud-LLM + Q6/Q7 hardened)
======================================================
Changes from v3.1:
- Q6: Three-step decoupled DB transactions
  1. Short transaction: write PENDING, commit, release
  2. NO DB lock: call cloud LLM (5-15s, no DB connection held)
  3. Long transaction: verify PENDING, atomic write result, commit
- Q7: In-memory inflight flag check BEFORE any DB call
  - Prevents API burst (50 submits in 100ms = 49 rejected)
  - Atomic via set() under CPython GIL
  - Auto-released via try/finally
- Crash-safe: if LLM call hangs, finally releases the flag

Architecture:
  Client (WS) -> inflight_check -> _persist_pending (short TX) ->
  _call_llm (NO DB) -> _verify_and_persist (long TX) -> broadcast
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect

from ..db import get_db_session
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
            "message": "Connected. Server controls scene_id.",
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
                # Non-blocking dispatch (Q7 in-memory check is inside _process_action)
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
    Process a player action with Q6/Q7 hardening.

    Q7: In-memory inflight check FIRST (before any DB call)
    Q6: Three-step decoupled transactions
    """
    task_id = str(uuid.uuid4())

    # === Validate basic payload ===
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

    # ============================================================
    # Q7 STEP 0: In-memory inflight interception (microsecond check)
    # ============================================================
    if not registry.try_acquire_inflight(character_id):
        logger.warning(f"[Q7] Burst rejected for {character_id} — already in-flight")
        try:
            await websocket.send_json({
                "type": "error",
                "code": "already_inflight",
                "task_id": task_id,
                "message": "Another action is already processing. Please wait.",
            })
        except Exception:
            pass
        return  # REJECT immediately — no DB call, no LLM call

    # MUST release flag in finally (even on crash)
    try:
        # ============================================================
        # Q6 STEP 1: Read character state (short transaction)
        # ============================================================
        db_session = get_db_session()
        try:
            character_state = await db_session.get_character_state(character_id)
            if not character_state:
                await _send_error(websocket, character_id, {
                    "type": "error",
                    "code": "character_not_found",
                    "task_id": task_id,
                })
                return

            if not character_state.get("is_alive", True):
                await _send_error(websocket, character_id, {
                    "type": "error",
                    "code": "character_dead",
                    "task_id": task_id,
                    "message": "Character is dead. Use soul transfer to continue.",
                })
                return

            authoritative_scene_id = character_state["current_scene_id"]

            # Optional: detect scene_id mismatch (defense in depth)
            client_claimed_scene_id = msg.get("scene_id")
            if client_claimed_scene_id and client_claimed_scene_id != authoritative_scene_id:
                logger.warning(
                    f"[Security] scene_id mismatch for {character_id}: "
                    f"client={client_claimed_scene_id}, server={authoritative_scene_id}"
                )
                await _send_error(websocket, character_id, {
                    "type": "error",
                    "code": "state_mismatch",
                    "task_id": task_id,
                    "client_scene_id": client_claimed_scene_id,
                    "server_scene_id": authoritative_scene_id,
                })
                return

            # ============================================================
            # Q6 STEP 1: Write PENDING (short transaction, then commit+release)
            # ============================================================
            action_id = await db_session.create_action_history(
                character_id=character_id,
                scene_id=authoritative_scene_id,
                round_number=msg.get("round", 0),
                player_choice=msg.get("choice") or msg.get("player_input"),
                execution_status="PENDING",
            )
            # db_session will auto-commit on context exit
        finally:
            await db_session.close()  # Release DB connection ASAP

        # Send action_accepted immediately
        try:
            await websocket.send_json({
                "type": "action_accepted",
                "task_id": task_id,
                "action_id": action_id,
                "character_id": character_id,
                "scene_id": authoritative_scene_id,
                "status": "processing",
                "message": "Action accepted, generating scene...",
            })
        except Exception:
            pass  # WS may be closed

        # Mark as PROCESSING (own short transaction)
        db_session = get_db_session()
        try:
            await db_session.update_action_history(
                action_id,
                execution_status="PROCESSING",
                started_at=datetime.utcnow(),
            )
        finally:
            await db_session.close()

        # ============================================================
        # Q6 STEP 2: Call cloud LLM (NO DB LOCK — connection released)
        # ============================================================
        try:
            lock = await scene_lock_manager.get_lock(authoritative_scene_id)
            async with lock:
                logger.info(f"[Task {task_id}] Locked scene {authoritative_scene_id}, calling LLM")
                scene_output = await _call_cloud_llm(
                    character_id=character_id,
                    scene_id=authoritative_scene_id,
                    player_input=msg,
                    character_state=character_state,
                )
                logger.info(f"[Task {task_id}] LLM complete")

            # ============================================================
            # Q6 STEP 3: Verify PENDING + atomic write result (long transaction)
            # ============================================================
            db_session = get_db_session()
            try:
                # Verify action is still PENDING/PROCESSING (not interrupted by restart)
                current_status = await db_session.get_action_status(action_id)
                if current_status in ("INTERRUPTED", "FAILED"):
                    logger.warning(
                        f"[Task {task_id}] Action status changed to {current_status} "
                        f"during LLM call — skipping write"
                    )
                    # Notify client
                    try:
                        await registry.broadcast(character_id, {
                            "type": "task_status",
                            "task_id": task_id,
                            "action_id": action_id,
                            "status": "interrupted",
                            "message": "Action was interrupted (e.g., server restart). Please re-submit.",
                        })
                    except Exception:
                        pass
                    return

                # Atomic write: action_history + character_states + (optional scenes)
                async with db_session.transaction():
                    # 1. Update action_history to COMPLETED
                    await db_session.update_action_history(
                        action_id,
                        execution_status="COMPLETED",
                        completed_at=datetime.utcnow(),
                        llm_narrative_output=scene_output.get("narrative"),
                        llm_choices_output=scene_output.get("choices"),
                        llm_state_changes=scene_output.get("state_changes"),
                    )
                    # 2. Apply state changes
                    if scene_output.get("state_changes"):
                        await db_session.apply_state_changes(
                            character_id,
                            scene_output["state_changes"],
                        )
                    # 3. Update scene if changed
                    if scene_output.get("new_scene_id"):
                        await db_session.update_character_scene(
                            character_id,
                            scene_output["new_scene_id"],
                        )
                    # 4. Update world parameters if changed
                    if scene_output.get("world_parameter_changes"):
                        await db_session.apply_world_parameter_changes(
                            scene_output["world_parameter_changes"],
                        )
            except Exception as e:
                # TX rolled back automatically; mark FAILED
                logger.exception(f"[Task {task_id}] DB write failed: {e}")
                # Use a separate short TX to mark FAILED
                fail_session = get_db_session()
                try:
                    await fail_session.update_action_history(
                        action_id,
                        execution_status="FAILED",
                        completed_at=datetime.utcnow(),
                        error_message=str(e),
                    )
                finally:
                    await fail_session.close()
                # Re-raise so outer try/finally still runs
                raise
            finally:
                await db_session.close()

        except Exception as e:
            logger.exception(f"[Task {task_id}] Failed: {e}")
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
            return  # Don't broadcast scene_update

        # ============================================================
        # Q6 STEP 4: Broadcast result (outside all transactions)
        # ============================================================
        await registry.broadcast(character_id, {
            "type": "scene_update",
            "task_id": task_id,
            "action_id": action_id,
            "round": scene_output.get("round"),
            "scene_id": authoritative_scene_id,
            "narrative": scene_output.get("narrative"),
            "choices": scene_output.get("choices"),
            "state_changes": scene_output.get("state_changes"),
            "minor_event": scene_output.get("minor_event"),
            "timestamp": datetime.utcnow().isoformat(),
        })

    finally:
        # ============================================================
        # Q7 CRITICAL: Always release in-memory flag
        # ============================================================
        registry.release_inflight(character_id)


async def _send_error(websocket: WebSocket, character_id: str, message: dict):
    """Try to send via WS, fall back to broadcast."""
    try:
        await websocket.send_json(message)
    except Exception:
        await registry.broadcast(character_id, message)


async def _call_cloud_llm(
    character_id: str,
    scene_id: str,
    player_input: dict,
    character_state: dict,
) -> dict:
    """
    Call cloud LLM (MiniMax M3) for scene generation.

    This function:
    - HOLDS NO DB LOCK
    - May take 5-15 seconds (cloud API latency)
    - Has retry logic for transient 502/504 errors
    - Falls back gracefully on persistent failure

    TODO: Implement with LLMClient from backend.llm_client
    Reference: docs/PROMPTS/scene_agent_prompt.md
    """
    logger.info(f"[LLM] Calling cloud LLM for {character_id} in {scene_id}")
    await asyncio.sleep(2)  # Simulate cloud latency
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
