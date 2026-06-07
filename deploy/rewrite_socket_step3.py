"""Surgical replacement of the STEP 1/2/3 blocks in game_socket.py
with raw-SQL engine.begin() versions that don't rely on the
AsyncSession ORM (which appears to silently swallow commits in
this version of SQLAlchemy 2.x on Windows + asyncpg).
"""
from pathlib import Path
import re

target = Path(r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\backend\ws\game_socket.py")
src = target.read_text(encoding="utf-8")

# ==================== STEP 1 block ====================
# Replace the Q6 STEP 1 ORM block with raw INSERT
old_step1 = re.search(
    r"# Q6 STEP 1: Write PENDING \(short transaction.*?# session will auto-commit on context exit\n",
    src,
    re.DOTALL,
)
new_step1 = """# Q6 STEP 1: Write PENDING (raw SQL — ORM commit was silently dropped)
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
"""
if old_step1:
    src = src[: old_step1.start()] + new_step1 + src[old_step1.end():]
    print("STEP 1 replaced.")
else:
    print("STEP 1 pattern not found — skipping.")

# ==================== Mark PROCESSING block ====================
old_proc = re.search(
    r"# Mark as PROCESSING \(own short transaction\)\n        async with AsyncSessionLocal\(\) as session:.*?await session\.commit\(\)\n",
    src,
    re.DOTALL,
)
new_proc = """# Mark as PROCESSING (raw SQL)
        from ..db import engine
        from sqlalchemy import text as _sql_text
        async with engine.begin() as conn:
            await conn.execute(
                _sql_text(
                    "UPDATE action_history SET execution_status = 'PROCESSING', "
                    "started_at = now() WHERE id = CAST(:id AS uuid)"
                ),
                {"id": str(action_id)},
            )
"""
if old_proc:
    src = src[: old_proc.start()] + new_proc + src[old_proc.end():]
    print("Mark PROCESSING replaced.")
else:
    print("Mark PROCESSING pattern not found — skipping.")

# ==================== STEP 3 long TX ====================
old_step3 = re.search(
    r"try:\n                # Use a single, dedicated session for the long TX.*?# Re-raise so outer try/finally still runs\n                raise\n",
    src,
    re.DOTALL,
)
new_step3 = '''try:
                # Use raw SQL via engine.begin() — the AsyncSession ORM
                # commits were silently dropped in this Windows + asyncpg
                # combo. Raw SQL gives us guaranteed commit semantics.
                from ..db import engine
                from sqlalchemy import text as _sql_text
                import json as _json
                async with engine.begin() as conn:
                    # Verify action is still PENDING/PROCESSING
                    row_status_result = await conn.execute(
                        _sql_text(
                            "SELECT execution_status FROM action_history "
                            "WHERE id = CAST(:id AS uuid)"
                        ),
                        {"id": str(action_id)},
                    )
                    current_status_row = row_status_result.first()
                    current_status = current_status_row[0] if current_status_row else None
                if current_status in ("INTERRUPTED", "FAILED"):
                    logger.warning(
                        f"[Task {task_id}] Action status changed to {current_status} "
                        f"during LLM call — skipping write"
                    )
                    try:
                        await registry.broadcast(
                            character_id,
                            {
                                "type": "task_status",
                                "task_id": task_id,
                                "action_id": str(action_id),
                                "status": "interrupted",
                                "message": "Action was interrupted (e.g., server restart). Please re-submit.",
                            },
                        )
                    except Exception:
                        pass
                    return

                # Atomic write: action_history + character_states + scene
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
                    # Apply state changes to character_states
                    if scene_output.get("state_changes"):
                        cs = scene_output["state_changes"]
                        for k, db_key, profile_section in (
                            ("stamina_level", "stamina_level", "physical"),
                            ("health_status", "health_status", "physical"),
                            ("morale_level", "morale_level", "mental"),
                        ):
                            if k in cs and cs[k]:
                                await conn.execute(
                                    _sql_text(
                                        "UPDATE character_states "
                                        "SET semantic_profile = jsonb_set("
                                        "    COALESCE(semantic_profile, '{}'::jsonb), "
                                        "    ARRAY[:section, :key]::text[], "
                                        "    to_jsonb(:val::text) "
                                        "), updated_at = now() "
                                        "WHERE character_id = :cid"
                                    ),
                                    {
                                        "section": profile_section,
                                        "key": db_key,
                                        "val": str(cs[k]),
                                        "cid": character_id,
                                    },
                                )
                    # Update scene if changed
                    if scene_output.get("new_scene_id"):
                        await conn.execute(
                            _sql_text(
                                "UPDATE character_states SET current_scene_id = :sid, "
                                "updated_at = now() WHERE character_id = :cid"
                            ),
                            {"sid": scene_output["new_scene_id"], "cid": character_id},
                        )
'''
if old_step3:
    src = src[: old_step3.start()] + new_step3 + src[old_step3.end():]
    print("STEP 3 replaced.")
else:
    print("STEP 3 pattern not found — skipping.")

# ==================== STEP 3 FAILED mark ====================
old_fail = re.search(
    r"except Exception as e:\n                # TX rolled back automatically; mark FAILED\n                logger\.exception.*?# Re-raise so outer try/finally still runs\n                raise\n",
    src,
    re.DOTALL,
)
new_fail = '''except Exception as e:
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
                raise
'''
if old_fail:
    src = src[: old_fail.start()] + new_fail + src[old_fail.end():]
    print("STEP 3 FAILED mark replaced.")
else:
    print("STEP 3 FAILED mark pattern not found — skipping.")

target.write_text(src, encoding="utf-8")
print("Done.")
