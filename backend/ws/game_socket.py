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

        # Phase L2-I/Phase B: register the character's current scene so
        # we can broadcast to other players in the same scene. If we
        # don't know it yet, leave it unset; it'll be set on the first
        # _process_action call.
        try:
            from . import _db_session_factory  # type: ignore  # noqa
        except ImportError:
            pass

        # Best-effort: read character state to discover current scene
        try:
            from ..db import AsyncSessionLocal
            from ..models import CharacterState
            from sqlalchemy import select
            async with AsyncSessionLocal() as session:
                stmt = select(CharacterState).where(
                    CharacterState.character_id == character_id
                )
                result = await session.execute(stmt)
                cs_row = result.scalar_one_or_none()
                if cs_row is not None:
                    scene_id = cs_row.current_scene_id
                    if scene_id:
                        await registry.set_scene(character_id, scene_id)
        except Exception as e:
            logger.warning(
                f"[WS {connection_id}] Could not pre-load scene for {character_id}: {e}"
            )

        await websocket.send_json(
            {
                "type": "connection_ack",
                "connection_id": connection_id,
                "character_id": character_id,
                "timestamp": datetime.utcnow().isoformat(),
                "message": "Connected. Server controls scene_id.",
            }
        )

        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {
                        "type": "error",
                        "code": "invalid_json",
                        "message": "Message must be valid JSON",
                    }
                )
                continue

            msg_type = msg.get("type")

            if msg_type == "ping":
                await websocket.send_json(
                    {
                        "type": "pong",
                        "ts": datetime.utcnow().isoformat(),
                    }
                )
                continue

            if msg_type == "action_submit":
                # Non-blocking dispatch (Q7 in-memory check is inside _process_action)
                asyncio.create_task(_process_action(websocket, character_id, msg, connection_id))
                continue

            await websocket.send_json(
                {
                    "type": "error",
                    "code": "unknown_message_type",
                    "message": f"Unknown message type: {msg_type}",
                }
            )

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
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "invalid_action",
                    "task_id": task_id,
                    "message": "Missing choice or player_input",
                }
            )
        except Exception:
            pass
        return

    # ============================================================
    # Q7 STEP 0: In-memory inflight interception (microsecond check)
    # ============================================================
    if not registry.try_acquire_inflight(character_id):
        logger.warning(f"[Q7] Burst rejected for {character_id} — already in-flight")
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "already_inflight",
                    "task_id": task_id,
                    "message": "Another action is already processing. Please wait.",
                }
            )
        except Exception:
            pass
        return  # REJECT immediately — no DB call, no LLM call

    # MUST release flag in finally (even on crash)
    try:
        # ============================================================
        # Q6 STEP 1: Read character state (short transaction)
        # ============================================================
        from ..db import AsyncSessionLocal
        from ..models import CharacterState
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            stmt = select(CharacterState).where(
                CharacterState.character_id == character_id
            )
            result = await session.execute(stmt)
            cs_row = result.scalar_one_or_none()
            if cs_row is None:
                await _send_error(
                    websocket,
                    character_id,
                    {
                        "type": "error",
                        "code": "character_not_found",
                        "task_id": task_id,
                    },
                )
                return

            character_state = {
                "character_id": cs_row.character_id,
                "name": cs_row.name,
                "world_id": cs_row.world_id,
                "current_scene_id": cs_row.current_scene_id,
                "is_alive": cs_row.is_alive,
                "is_npc_mode": cs_row.is_npc_mode,
                "semantic_profile": cs_row.semantic_profile,
            }

            if not character_state.get("is_alive", True):
                await _send_error(
                    websocket,
                    character_id,
                    {
                        "type": "error",
                        "code": "character_dead",
                        "task_id": task_id,
                        "message": "Character is dead. Use soul transfer to continue.",
                    },
                )
                return

            authoritative_scene_id = character_state["current_scene_id"]

            # Optional: detect scene_id mismatch (defense in depth)
            client_claimed_scene_id = msg.get("scene_id")
            if client_claimed_scene_id and client_claimed_scene_id != authoritative_scene_id:
                logger.warning(
                    f"[Security] scene_id mismatch for {character_id}: "
                    f"client={client_claimed_scene_id}, server={authoritative_scene_id}"
                )
                await _send_error(
                    websocket,
                    character_id,
                    {
                        "type": "error",
                        "code": "state_mismatch",
                        "task_id": task_id,
                        "client_scene_id": client_claimed_scene_id,
                        "server_scene_id": authoritative_scene_id,
                    },
                )
                return

            # ============================================================
            # Q6 STEP 1: Write PENDING (raw SQL — ORM commit was silently dropped)
            from ..db import engine
            from sqlalchemy import text as _sql_text
            import uuid as _uuid
            import json as _json
            action_id = _uuid.uuid4()
            choice_payload = msg.get("choice") or msg.get("player_input") or {}
            player_choice_json = _json.dumps(choice_payload, ensure_ascii=False, default=str)
            async with engine.begin() as conn:
                await conn.execute(
                    _sql_text(
                        "INSERT INTO action_history "
                        "(id, character_id, scene_id, round_number, player_choice, "
                        " execution_status, submitted_at, created_at) "
                        "VALUES (CAST(:id AS uuid), :cid, :sid, :rnd, CAST(:pc AS jsonb), "
                        "        :st, now(), now())"
                    ),
                    {
                        "id": str(action_id),
                        "cid": character_id,
                        "sid": authoritative_scene_id,
                        "rnd": int(msg.get("round", 0) or 0),
                        "pc": player_choice_json,
                        "st": "PENDING",
                    },
                )

        # Send action_accepted immediately
        try:
            await websocket.send_json(
                {
                    "type": "action_accepted",
                    "task_id": task_id,
                    "action_id": str(action_id),
                    "character_id": character_id,
                    "scene_id": authoritative_scene_id,
                    "status": "processing",
                    "message": "Action accepted, generating scene...",
                }
            )
        except Exception:
            pass  # WS may be closed

        # Mark as PROCESSING (raw SQL)
        from ..db import engine
        from sqlalchemy import text as _sql_text
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    _sql_text(
                        "UPDATE action_history SET execution_status = 'PROCESSING', "
                        "started_at = now() WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": str(action_id)},
                )
        except Exception as e:
            logger.exception(f"[Task {task_id}] Failed: {e}")
            try:
                await registry.broadcast(
                    character_id,
                    {
                        "type": "task_status",
                        "task_id": task_id,
                        "action_id": str(action_id),
                        "status": "failed",
                        "error": str(e),
                    },
                )
            except Exception:
                pass
            return  # Don't broadcast scene_update

        # ============================================================
        # Q6 STEP 2 + 3: Call LLM, then atomic write
        # ============================================================
        scene_output: dict = {}
        try:
            from .scene_locks import scene_lock_manager
            from ..llm_client import get_llm_client
            lock = await scene_lock_manager.get_lock(authoritative_scene_id)
            async with lock:
                logger.info(
                    f"[Task {task_id}] Locked scene {authoritative_scene_id}, calling LLM"
                )
                client = get_llm_client()
                # Build a rich system_prompt + user_message that
                # carries the FULL game context. Without this, M3
                # has no memory of prior rounds, the scene state,
                # or the character's current profile — so every
                # response is a cold start (generic 'you stand in
                # a tavern...' rather than a continuation of the
                # actual story).
                from sqlalchemy import text as _sql_text_ctx
                from ..db import engine as _engine

                # 1. Load scene description
                scene_desc = ""
                try:
                    async with _engine.begin() as conn:
                        r = await conn.execute(
                            _sql_text_ctx(
                                "SELECT name, description, atmosphere FROM scenes WHERE id = :sid"
                            ),
                            {"sid": authoritative_scene_id},
                        )
                        row = r.first()
                        if row:
                            scene_desc = f"場景名: {row[0]}\n場景描述: {row[1]}\n氣氛: {row[2] or 'neutral'}"
                except Exception:
                    pass

                # 2. Load last 3 actions for context
                prior_actions = []
                try:
                    async with _engine.begin() as conn:
                        r = await conn.execute(
                            _sql_text_ctx(
                                "SELECT round_number, player_choice, llm_narrative_output "
                                "FROM action_history WHERE character_id = :cid "
                                "ORDER BY created_at DESC LIMIT 3"
                            ),
                            {"cid": character_id},
                        )
                        for row in r:
                            prior_actions.append({
                                "round": row[0],
                                "choice": row[1],
                                "narrative": row[2],
                            })
                except Exception:
                    pass

                # 3. Build the strong prompt
                sem = character_state.get("semantic_profile") or {}
                phys = sem.get("physical", {}) or {}
                ment = sem.get("mental", {}) or {}
                system_prompt = (
                    "你是 OpenClaw Sandbox RPG 的敘事者。\n"
                    "請用繁體中文（粵語风格）回應，narrative 至少 3-4 句以豐富場景描述。\n"
                    "\n"
                    "## 強制規則\n"
                    "1. **只返回 JSON**。不要有任何解釋、思考、Markdown 包装。\n"
                    "2. JSON 形狀:\n"
                    '   {"narrative": "<一段敘事文字 3-4 句>", '
                    '"choices": [{"id": "opt_1", "vignette": "<選擇 1 句>"}, ...], '
                    '"state_changes": {"stamina_level": "<stamina>" | null, '
                    '"health_status": "<status>" | null, '
                    '"morale_level": "<morale>" | null}, '
                    '"new_scene_id": "<scene_id>" | null}\n'
                    "3. **choices 必須有 4 個，每個方向唔同**，不可為空。\n"
                    "   建議 4 個方向:\n"
                    "   - 1 個 **戰鬥/動作** 方向 (action: 攻擊、施法、逃跑)\n"
                    "   - 1 個 **社交/對話** 方向 (talk: 問路、求助、欺騙)\n"
                    "   - 1 個 **探索/調查** 方向 (explore: 搜查、跟蹤、發掘)\n"
                    "   - 1 個 **創意/異想天開** 方向 (creative: 玩遊戲、講笑話、奇怪主意)\n"
                    "4. narrative 必須是完整段落，不可以包含<think>開頭的思考。\n"
                    "5. 請延續之前的劇情（見 user_message 嘅 prior_actions），"
                    "不要無關聯地重新開始。\n"
                    "\n"
                    f"## 當前角色\n"
                    f"名字: {character_state.get('name', character_id)}\n"
                    f"體力: {phys.get('stamina_level', 'fresh')}\n"
                    f"健康: {phys.get('health_status', 'healthy')}\n"
                    f"士氣: {ment.get('morale_level', 'calm')}\n"
                    "\n"
                    f"## 當前場景\n"
                    f"{scene_desc or authoritative_scene_id}\n"
                    "\n"
                    "## 範例 (few-shot)\n"
                    "若玩家站在酒館門口，4 個選擇可以是:\n"
                    '  {"id": "opt_1", "vignette": "推門進去問吧枱老闆消息"}\n'
                    '  {"id": "opt_2", "vignette": "從側窗偷窺酒館內部動靜"}\n'
                    '  {"id": "opt_3", "vignette": "敲門前先整理裝備"}\n'
                    '  {"id": "opt_4", "vignette": "扮成吟遊詩人混入酒館"}\n'
                )

                # 4. Build the rich user_message that carries the
                # previous round's narrative + the choice being made.
                choice_obj = msg.get("choice") or msg.get("player_input") or {}
                user_message_parts = []
                if prior_actions:
                    user_message_parts.append("## 之前的劇情 (prior_actions)\n")
                    for pa in reversed(prior_actions):
                        user_message_parts.append(
                            f"- Round {pa['round']}: 玩家選擇: {json.dumps(pa['choice'], ensure_ascii=False)[:200]}\n"
                            f"  結果: {(pa['narrative'] or '(no narrative)')[:300]}\n"
                        )
                user_message_parts.append("\n## 玩家嘅最新選擇 (current choice)\n")
                user_message_parts.append(json.dumps(choice_obj, ensure_ascii=False))
                user_message = "\n".join(user_message_parts)

                raw = await client.generate(
                    system_prompt=system_prompt,
                    user_message=user_message,
                )
                # Phase L2-E hotfix: M3 with thinking mode often prepends
                # \n<think>\n... to the output. We strip thinking blocks
                # first, then attempt JSON parse, then a strict regex
                # search for a JSON object in the cleaned text.
                import re as _re
                cleaned = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
                cleaned = _re.sub(r"^<think>.*?(?=\n\n|\Z)", "", cleaned, flags=_re.DOTALL).strip()
                # Find first '{' and the matching '}' (balanced braces)
                scene_output: dict = {}
                if cleaned:
                    # Find a JSON object
                    start = cleaned.find("{")
                    if start != -1:
                        depth = 0
                        in_string = False
                        escape = False
                        for end in range(start, len(cleaned)):
                            ch = cleaned[end]
                            if escape:
                                escape = False
                                continue
                            if ch == "\\":
                                escape = True
                                continue
                            if ch == '"':
                                in_string = not in_string
                                continue
                            if in_string:
                                continue
                            if ch == "{":
                                depth += 1
                            elif ch == "}":
                                depth -= 1
                                if depth == 0:
                                    try:
                                        scene_output = json.loads(cleaned[start : end + 1])
                                    except json.JSONDecodeError:
                                        pass
                                    break
                if not scene_output:
                    # Last-resort fallback: treat the whole cleaned
                    # response as a narrative with NO choices. This
                    # is degraded but at least the player sees
                    # something instead of an infinite spinner.
                    scene_output = {
                        "narrative": (cleaned or raw)[:500],
                        "choices": [],
                        "state_changes": {},
                        "new_scene_id": None,
                    }
                # Always provide 4 choices (the SPA renders 4
                # choice cards; fewer breaks the layout). Pad with
                # safe defaults if the LLM returned fewer.
                while len(scene_output.get("choices", [])) < 4:
                    scene_output.setdefault("choices", []).append(
                        {
                            "id": f"opt_fallback_{len(scene_output.get('choices', [])) + 1}",
                            "vignette": "繼續觀察環境",
                            "intent_category": "exploration",
                        }
                    )
                logger.info(f"[Task {task_id}] LLM complete")
        except Exception as e:
            logger.exception(f"[Task {task_id}] LLM call failed: {e}")
            # Mark FAILED
            try:
                from ..db import engine
                from sqlalchemy import text as _sql_text
                async with engine.begin() as conn:
                    await conn.execute(
                        _sql_text(
                            "UPDATE action_history SET execution_status = 'FAILED', "
                            "completed_at = now(), error_message = :err "
                            "WHERE id = CAST(:id AS uuid)"
                        ),
                        {"err": f"llm_call_failed: {e}"[:500], "id": str(action_id)},
                    )
            except Exception:
                pass
            return  # Don't broadcast

        # Q6 STEP 3: write to DB
        try:
            from ..db import engine
            from sqlalchemy import text as _sql_text
            import json as _json
            async with engine.begin() as conn:
                choices_json = _json.dumps(
                    scene_output.get("choices", []), ensure_ascii=False, default=str
                )
                state_changes_json = _json.dumps(
                    scene_output.get("state_changes", {}), ensure_ascii=False, default=str
                )
                await conn.execute(
                    _sql_text(
                        "UPDATE action_history SET execution_status = 'COMPLETED', "
                        "completed_at = now(), "
                        "llm_narrative_output = :narrative, "
                        "llm_choices_output = CAST(:choices AS jsonb), "
                        "llm_state_changes = CAST(:state AS jsonb) "
                        "WHERE id = CAST(:id AS uuid)"
                    ),
                    {
                        "narrative": scene_output.get("narrative", ""),
                        "choices": choices_json,
                        "state": state_changes_json,
                        "id": str(action_id),
                    },
                )
                if scene_output.get("state_changes"):
                    cs = scene_output["state_changes"]
                    for k, db_key, profile_section in (
                        ("stamina_level", "stamina_level", "physical"),
                        ("health_status", "health_status", "physical"),
                        ("morale_level", "morale_level", "mental"),
                    ):
                        if k in cs and cs[k]:
                            # Build the path as a SQL ARRAY literal.
                            # jsonb_set needs a real ARRAY[...] expression,
                            # not bound positional params — asyncpg does
                            # not allow bound params inside an ARRAY
                            # literal. The values are constants, not
                            # user-controlled, so string concat is safe.
                            path_array = (
                                "ARRAY['" + profile_section
                                + "','" + db_key + "']::text[]"
                            )
                            # Cast :val explicitly to text via SQL fragment
                            # (asyncpg's bind params don't support inline ::text
                            # casts). Build the value as a quoted SQL literal
                            # since :val is always a primitive (str from M3).
                            val_literal = "'" + str(cs[k]).replace("'", "''") + "'::text"
                            await conn.execute(
                                _sql_text(
                                    "UPDATE character_states "
                                    "SET semantic_profile = jsonb_set("
                                    "    COALESCE(semantic_profile, '{}'::jsonb), "
                                    "    " + path_array + ", "
                                    "    to_jsonb(" + val_literal + ") "
                                    "), updated_at = now() "
                                    "WHERE character_id = :cid"
                                ),
                                {
                                    "cid": character_id,
                                },
                            )
                if scene_output.get("new_scene_id"):
                    new_sid = scene_output["new_scene_id"]
                    # Phase L2-E hotfix: validate the scene exists in DB
                    # before updating character_states.current_scene_id.
                    # Without this, an M3-invented scene slug like
                    # 'loc_phandalin_town_square' would crash with
                    # ForeignKeyViolationError mid-transaction, the
                    # whole Q6 STEP 3 TX would roll back, and the
                    # scene_update broadcast never fires — leaving
                    # the player on a permanent 'handling...' spinner.
                    scene_check = await conn.execute(
                        _sql_text("SELECT 1 FROM scenes WHERE id = :sid"),
                        {"sid": new_sid},
                    )
                    if scene_check.first() is not None:
                        await conn.execute(
                            _sql_text(
                                "UPDATE character_states SET current_scene_id = :sid, "
                                "updated_at = now() WHERE character_id = :cid"
                            ),
                            {"sid": new_sid, "cid": character_id},
                        )
                    else:
                        # M3 invented a scene the DB doesn't have.
                        # Skip the scene update (keep the player in
                        # their current scene) and just log the warning.
                        # The narrative still ships to the player.
                        logger.warning(
                            f"[Task {task_id}] M3 returned unknown scene_id "
                            f"'{new_sid}' — keeping current scene '{authoritative_scene_id}'"
                        )
        except Exception as e:
            logger.exception(f"[Task {task_id}] DB write failed: {e}")
            try:
                from ..db import engine
                from sqlalchemy import text as _sql_text
                async with engine.begin() as conn:
                    await conn.execute(
                        _sql_text(
                            "UPDATE action_history SET execution_status = 'FAILED', "
                            "completed_at = now(), error_message = :err "
                            "WHERE id = CAST(:id AS uuid)"
                        ),
                        {"err": str(e)[:500], "id": str(action_id)},
                    )
            except Exception:
                pass
            return  # Don't broadcast

        # ============================================================
        # Q6 STEP 4: Broadcast result (outside all transactions)
        # ============================================================
        await registry.broadcast(
            character_id,
            {
                "type": "scene_update",
                "task_id": task_id,
                "action_id": str(action_id),
                "round": scene_output.get("round"),
                "scene_id": authoritative_scene_id,
                "narrative": scene_output.get("narrative"),
                "choices": scene_output.get("choices"),
                "state_changes": scene_output.get("state_changes"),
                "minor_event": scene_output.get("minor_event"),
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        # Phase L2-I/Phase B: update the character's current scene in
        # the registry so future cross-player broadcasts go to the
        # right audience.
        if scene_output.get("new_scene_id"):
            await registry.set_scene(
                character_id, scene_output["new_scene_id"]
            )
        else:
            await registry.set_scene(character_id, authoritative_scene_id)

        # Phase L2-I/Phase B: cross-player broadcast. Notify everyone
        # else in the same scene that this character took an action.
        # The recipient clients use this to update their "other player
        # activity" sidebar (Phase B-5). We do NOT include the full
        # scene_output here (each player will get their own next round
        # when they submit); we only include the action's narrative
        # summary so others can react.
        actor_choice = msg.get("choice") or msg.get("player_input") or {}
        choice_text = (
            actor_choice.get("vignette")
            or actor_choice.get("text")
            or (actor_choice.get("id") if isinstance(actor_choice, dict) else None)
            or "took an action"
        )
        sent = await registry.broadcast_to_scene(
            authoritative_scene_id,
            {
                "type": "other_player_action",
                "task_id": task_id,
                "actor_character_id": character_id,
                "actor_name": character_state.get("name", character_id),
                "scene_id": authoritative_scene_id,
                "choice_text": choice_text,
                "world_event": scene_output.get("minor_event"),
                "world_state_change": (
                    bool(scene_output.get("state_changes"))
                ),
                "timestamp": datetime.utcnow().isoformat(),
            },
            exclude_character_id=character_id,
        )
        if sent:
            logger.info(
                f"[Phase B] Broadcast {character_id}'s action to "
                f"{sent} other player(s) in {authoritative_scene_id}"
            )

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
                "attitude_options": [{"dimension": "caution", "level": "careful"}],
            }
        ],
        "state_changes": {},
        "minor_event": None,
    }
