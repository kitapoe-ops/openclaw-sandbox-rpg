"""
Action Processor v2.0 — Real HTTP /api/action/process pipeline (Phase E1 + F3)
================================================================================

This module is the *real* action processor that backs the
``POST /api/action/process`` HTTP route. It is the HTTP analogue of
the WebSocket ``/ws/game/{character_id}`` handler in
:mod:`backend.ws.game_socket` — both call the same pipeline:

  1. **Validate** the verb against a whitelist (state-machine rule gate).
  2. **Serialize** per-scene physics lock (concurrency gate).
  3. **Phase F3:** Pull the character's current semantic state from
     the injected :class:`backend.state_machine.SemanticStateMachine`.
  4. **Phase F3:** Build the system prompt with
     :class:`backend.prompt_builder.PromptBuilder` so the LLM sees
     the current state at the top (F4 invariant).
  5. **Phase F3:** Call the LLM via
     :meth:`backend.llm_client.LLMClient.generate_with_state_contract`
     so the response is validated against the F1 ``StateMutation``
     schema. Bad mutations are dropped (F3 defense D2).
  6. **Phase F3:** Apply the validated mutation to the state machine
     and feed Memory Palace with the state-anchored summary (F1
     defense D3).
  7. **Update** the turn system (submit + complete a turn).
  8. **Return** ``{status, action_id, narrative, side_effects,
     mutation, mutation_error}``.

Phase F3 wiring
---------------
This module was UNFROZEN in Phase F3 to integrate:

  * ``PromptBuilder`` (F4) — system prompt is built with the
    current state at the top.
  * ``SemanticStateMachine`` (F1) — current state is read, and
    validated mutations are applied.
  * ``LLMClient.generate_with_state_contract`` (F3) — the
    ``StateMutation`` JSON contract is enforced on the LLM output.

The new constructor args (``state_machine``, ``prompt_builder``) are
optional for backward compatibility. If absent, the processor falls
back to the F1 minimum-viable path (no state, no prompt builder, no
state-contract LLM call) — this keeps the existing E1 tests green
without rewiring every fixture.

Why a new module (and not edit ``api/action.py``)
-------------------------------------------------
``backend/api/action.py`` is **frozen** per the Phase D1/D3/D4 Hard
Constraints. Its ``submit_action`` is a documented echo used by the
demo.html HTTP fallback. We do **not** modify that echo — instead we
ship a *second* endpoint (``/api/action/process``) backed by this
module. The wire-up lives in :mod:`backend.app_with_memory` (which
*is* editable), mirroring the Phase D4 v2 ``/api/character-list/``
pattern.

Why an injectable ``memory_palace`` and ``turn_system``
--------------------------------------------------------
Both are optional. In a hermetic test environment you can pass
``None`` (the default) and the processor will:

  * Skip Memory Palace persistence (no Postgres / no vector store).
  * Build an in-memory turn-system surrogate that tracks the
    ``active_turn_id`` per character in a plain dict.

This keeps the action processor testable without spinning up the
full D6/C2/C3 plumbing. Production wire-up (in
:mod:`backend.app_with_memory`) passes real instances via the
factory function ``build_default_processor()``.

Concurrency: per-scene physics lock
------------------------------------
Two simultaneous ``process()`` calls for the same character will
serialize on the asyncio lock keyed by ``character_id`` (we use the
character_id as the scene surrogate in this single-player
endpoint; multi-player scenes would use the scene_id from
``DEMO_STARTER``). See ``test_process_concurrent_actions_serialized``.

Note: the actual ``SceneLockManager`` (per-scene locks) lives in
:mod:`backend.ws.scene_locks`; we don't import it here because the
new HTTP endpoint is per-character, not per-scene, and we don't
want a cycle through ``backend.ws``.

R1 audit (Phase E1 pre-flight) — findings still addressed:
  * **CRITICAL #1** — verb validation via explicit whitelist, raises
    ``HTTPException(400)`` on unknown verbs.
  * **HIGH #2** — UUID4 ``action_id`` returned to client; Pydantic
    schema enforces non-empty character_id (422) and 1-50 char
    verb range.
  * **HIGH #3** — LLM call is wrapped in try/except; on failure we
    return ``HTTPException(500)`` with a useful error string instead
    of leaking the exception. The response is always JSON-shaped.
  * **MEDIUM #4** — physics lock prevents double-processing; the
    test ``test_process_concurrent_actions_serialized`` enforces it.
  * **INFO #5** — no ``/api/action/submit`` echo is touched; the
    legacy endpoint is preserved bit-for-bit.

Phase F3 added defenses (carried from F1):
  * **D2** — strict ``StateMutation`` validation. Bad LLM output
    (invalid JSON, extra fields, oversized tags, non-CJK chars) is
    dropped, but the narrative is still returned. No partial
    mutations.
  * **D3** — Memory Palace is fed with the state-anchored summary,
    not the raw narrative, to prevent vector pollution.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

# 5-module user prompt (2026-06-08). NARRATIVE_PROMPT_TEMPLATE below
# is preserved for backward compatibility; the active builder is
# :func:`backend.prompt_user.build_user_prompt`.
from ..prompt_user import build_user_prompt as build_user_prompt_5module
from ..prompt_user import ALLOWED_CHOICE_DIRECTIONS

logger = logging.getLogger(__name__)


# ============================================
# Whitelist — the verb gate (state-machine rule)
# ============================================
# In the full app, the state machine in :mod:`backend.state_machine`
# would gate verbs against per-character state (e.g. an unconscious
# character cannot ``attack``). We don't replicate that here because
# ``state_machine.py`` is frozen; a per-character dynamic gate can
# be added later without changing the public interface. The
# whitelist below is the *static* gate (D&D-style verbs).
ALLOWED_VERBS: frozenset[str] = frozenset(
    {
        "look",
        "examine",
        "move",
        "go",
        "walk",
        "run",
        "flee",
        "talk",
        "ask",
        "tell",
        "say",
        "negotiate",
        "intimidate",
        "attack",
        "cast",
        "use",
        "drink",
        "eat",
        "take",
        "drop",
        "open",
        "close",
        "search",
        "rest",
        "wait",
        "inventory",
        "equip",
        "unequip",
        "buy",
        "sell",
        "trade",
    }
)

# Narrative prompt template — kept simple and provider-agnostic.
# The full D6 prompt (with few-shots + JSON response_format) is the
# job of the LLMClient itself; this is the *user-message* side.
#
# NOTE (2026-06-08): NARRATIVE_PROMPT_TEMPLATE is preserved for
# backward compatibility (other modules / tests import it). The
# active builder is :func:`backend.prompt_user.build_user_prompt`,
# which produces the 5-module user prompt structure.
NARRATIVE_PROMPT_TEMPLATE = (
    "Player action: {verb} {target}{args_str}\n"
    "Character: {character_id}\n"
    "Scene context: {scene_context}\n"
    "Narrate the outcome in 1-3 sentences, in second-person, "
    "in a D&D-style tone. End with one or two possible follow-ups."
)


def _validate_and_extract_choices(raw_choices: Any) -> list[dict[str, str]]:
    """Validate and extract the LLM's ``choices`` array (2026-06-08).

    The 5-module user prompt asks for exactly 4 follow-up options
    with shape ``{direction: combat|social|explore|creative, vignette: str}``.

    This helper enforces:
    * Must be a list.
    * Each entry must be a dict with ``direction`` (one of the
      allowed directions) and ``vignette`` (non-empty string).
    * Unknown directions are dropped (and the entry is excluded
      from the returned list).
    * No numeric risk/reward values are allowed in the vignette
      (per module 5: "Risks: 每一個選項中只能文字描述，不可提供數字").
      We do a soft-check that strips entries with obvious numeric
      content; this is a best-effort guard, not a full parser.

    Returns
    -------
    list[dict[str, str]]
        Up to 4 validated choice dicts, in the order returned by
        the LLM. If the LLM returned fewer than 4, the list may
        be shorter; the caller is responsible for any
        "fill-in-default" UI behavior.
    """
    if not isinstance(raw_choices, list):
        return []
    validated: list[dict[str, str]] = []
    for entry in raw_choices[:4]:  # cap at 4
        if not isinstance(entry, dict):
            continue
        direction = entry.get("direction")
        vignette = entry.get("vignette")
        if not isinstance(direction, str) or direction not in ALLOWED_CHOICE_DIRECTIONS:
            continue
        if not isinstance(vignette, str) or not vignette.strip():
            continue
        # Soft check: vignette must not be predominantly numeric.
        # The user-prompt Module 5 says "Risks ... 不可提供數字" — i.e.
        # the LLM is told to keep risk descriptions text-only. We drop
        # entries whose character-level digit ratio exceeds 50% AND
        # the total length is >= 5 chars (a short tag like "v1" or
        # "hp" is preserved; a long numeric-heavy string is not).
        stripped = vignette.strip()
        if not stripped:
            continue
        if len(stripped) >= 5:
            digit_count = sum(1 for ch in stripped if ch.isdigit())
            if digit_count / len(stripped) > 0.5:
                logger.warning(
                    "Dropping choice vignette with high numeric content "
                    "(direction=%s, vignette=%r)",
                    direction,
                    stripped[:80],
                )
                continue
        validated.append({"direction": direction, "vignette": stripped})
    return validated


# ============================================
# Pydantic request / response models
# ============================================


class ProcessActionRequest(BaseModel):
    """POST /api/action/process request body.

    ``character_id`` is required. ``verb`` is required and bounded to
    1-50 chars (matches the whitelist's longest entry "intimidate"=10
    with headroom for future verbs). ``target`` and ``args`` are
    optional — bare ``look`` or ``inventory`` are valid actions.
    """

    character_id: str = Field(..., min_length=1, max_length=128)
    verb: str = Field(..., min_length=1, max_length=50)
    target: str | None = None
    args: dict[str, Any] | None = None


class ProcessActionResponse(BaseModel):
    """POST /api/action/process response body.

    Phase F3 adds two new fields:

      * ``mutation`` — the validated ``StateMutation`` (as a dict)
        that was applied to the character's state, or ``None`` if
        the LLM did not emit a valid one for this turn.
      * ``mutation_error`` — a short string describing why the
        mutation was rejected, or ``None`` if it was applied.

    The legacy fields (``status``, ``action_id``, ``narrative``,
    ``side_effects``, ``received``) are preserved bit-for-bit for
    backward compatibility with the E1 frozen response shape.
    """

    status: str = "processed"
    action_id: str
    narrative: str
    side_effects: list[dict[str, Any]] = Field(default_factory=list)
    # Debug-friendly echoes (kept stable for the frontend picker).
    received: dict[str, Any] = Field(default_factory=dict)
    # Phase F3: state mutation contract result. ``mutation`` is a
    # dict-shaped StateMutation; ``mutation_error`` is a short reason
    # if the mutation was rejected.
    mutation: dict[str, Any] | None = None
    mutation_error: str | None = None


# ============================================
# Errors
# ============================================


class ActionProcessorError(Exception):
    """Base for processor-level errors that should surface as HTTP 500."""


class LLMUnavailableError(ActionProcessorError):
    """The injected LLMClient raised during generate() — wraps the cause."""


# ============================================
# Turn-system surrogate (in-memory)
# ============================================


class InMemoryTurnSystem:
    """Minimal per-character turn tracker.

    Tracks the active turn id per character and prevents re-entrant
    processing. Mirrors the contract of the real
    :class:`backend.turn_system.TurnSystem` *just enough* for the
    action processor's needs: ``begin(character_id)`` returns an
    ``action_id`` if the slot is free, ``None`` if a turn is already
    active; ``end(character_id, action_id)`` releases the slot.

    The real TurnSystem (SQLite-backed) is used in production via
    :func:`build_default_processor`; tests use this surrogate.
    """

    def __init__(self) -> None:
        self._active: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def begin(self, character_id: str) -> str | None:
        """Claim a turn slot. Returns action_id if free, None if busy."""
        async with self._lock:
            if self._active.get(character_id):
                return None
            action_id = str(uuid.uuid4())
            self._active[character_id] = action_id
            return action_id

    async def end(self, character_id: str, action_id: str) -> None:
        """Release the turn slot. Safe to call even if not held."""
        async with self._lock:
            # Only clear if we still own it (defensive).
            if self._active.get(character_id) == action_id:
                del self._active[character_id]

    def active_for(self, character_id: str) -> str | None:
        return self._active.get(character_id)


# ============================================
# Main processor
# ============================================


class ActionProcessor:
    """Real HTTP action processor — runs the same pipeline as WS.

    Constructor takes injectable dependencies so tests can wire in
    mocks (LLMClient, MemoryPalaceIntegration) without monkey-patching
    module globals. ``build_default_processor()`` constructs the
    production instance from env / lazy globals.

    Phase F3 added two optional constructor args:

      * ``state_machine`` — a :class:`backend.state_machine.
        SemanticStateMachine` instance (or a duck-typed equivalent).
        The processor reads the current state from this machine and
        applies validated ``StateMutation`` instances to it. If
        ``None``, the F3 integration is disabled (legacy E1 path).
      * ``prompt_builder`` — a :class:`backend.prompt_builder.
        PromptBuilder` instance. The processor delegates system
        prompt construction to it. If ``None``, a default builder is
        used (which renders the F4 template with a stub memory
        palace).
    """

    def __init__(
        self,
        llm_client: Any,
        memory_palace: Any = None,
        turn_system: Any = None,
        scene_context_fn: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
        allowed_verbs: frozenset[str] | None = None,
        state_machine: Any = None,
        prompt_builder: Any = None,
    ) -> None:
        self.llm_client = llm_client
        self.memory_palace = memory_palace
        self.turn_system = turn_system or InMemoryTurnSystem()
        self._scene_context_fn = scene_context_fn
        self.allowed_verbs = allowed_verbs or ALLOWED_VERBS
        # Per-character concurrency gate (physics lock surrogate).
        self._character_locks: dict[str, asyncio.Lock] = {}
        self._locks_meta_lock = asyncio.Lock()
        # Phase F3: state machine + prompt builder.
        self._state_machine = state_machine
        self._prompt_builder = prompt_builder
        # Cache the LLM-contract capability check. If the LLM client
        # does NOT support ``generate_with_state_contract`` (e.g. a
        # test double that only implements the old interface), we
        # fall back to the legacy E1 ``generate()`` call. This keeps
        # the new constructor backward compatible.
        self._llm_supports_state_contract = hasattr(llm_client, "generate_with_state_contract")

    # ---------------------- public API ----------------------

    async def process(
        self,
        character_id: str,
        verb: str,
        target: str | None = None,
        args: dict[str, Any] | None = None,
        max_retries: int | None = None,
    ) -> dict[str, Any]:
        """Run the full pipeline. Returns the response dict.

        Raises ``HTTPException(400)`` on invalid verb. Raises
        ``HTTPException(500)`` on LLM failure (wrapped as
        ``LLMUnavailableError``). Raises ``HTTPException(409)`` if a
        previous action for this character is still in flight (the
        physics lock is held).

        Phase G1: ``max_retries`` is passed through to
        ``generate_with_state_contract`` so the LLM can self-correct
        on a dropped mutation. Defaults to ``None``, which lets the
        LLM client apply its own default (currently 2). Pass 0 to
        disable retry entirely (F3 behaviour).
        """
        # 1) Validate the verb (state-machine rule gate).
        verb_norm = verb.strip().lower()
        if verb_norm not in self.allowed_verbs:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid verb {verb!r}. "
                    f"Allowed verbs (first 10): "
                    f"{sorted(self.allowed_verbs)[:10]}..."
                ),
            )

        # 2) Acquire the per-character physics lock. Concurrent calls
        # for the same character SERIALIZE (they wait, they don't get
        # rejected) — that's the contract of the physics lock. The
        # WS handler in game_socket.py does the same thing with the
        # per-scene SceneLockManager; we mirror it here per-character
        # for the single-player HTTP endpoint.
        char_lock = await self._get_character_lock(character_id)
        async with char_lock:
            return await self._process_locked(
                character_id=character_id,
                verb=verb_norm,
                target=target,
                args=args,
                max_retries=max_retries,
            )

    # ---------------------- internals ----------------------

    async def _process_locked(
        self,
        character_id: str,
        verb: str,
        target: str | None,
        args: dict[str, Any] | None,
        max_retries: int | None = None,
    ) -> dict[str, Any]:
        # 3) Claim a turn in the turn system.
        action_id = await self.turn_system.begin(character_id)
        if action_id is None:
            # Should not happen — we hold the character lock, but
            # defensive: turn system says someone else owns it.
            raise HTTPException(
                status_code=409,
                detail=f"Turn slot for {character_id!r} is busy.",
            )

        side_effects: list[dict[str, Any]] = []
        mutation_dict: dict[str, Any] | None = None
        mutation_error: str | None = None
        try:
            # 4) Resolve scene context (if a hook is wired).
            scene_ctx: dict[str, Any] = {}
            if self._scene_context_fn is not None:
                try:
                    scene_ctx = await self._scene_context_fn(character_id)
                except Exception as exc:  # noqa: BLE001 — best-effort
                    logger.warning(
                        "scene_context_fn(%s) failed: %s; using empty context",
                        character_id,
                        exc,
                    )

            # 5) Build the user-message prompt (5-module structure, 2026-06-08).
            # The system prompt is built by PromptBuilder (F3 step 6);
            # the user message now uses the 5-module structure defined in
            # :mod:`backend.prompt_user` (Hard Facts, Karma & Traces,
            # Trigger Action, Director's Constraints, Output Requirements).
            # See :func:`backend.prompt_user.build_user_prompt` for the
            # section formatters.
            args_str = ""
            if args:
                # Keep it human-readable; never include raw user
                # data untruncated (D5 #2 lesson).
                try:
                    args_str = " with " + ", ".join(f"{k}={v}" for k, v in args.items())
                except Exception:
                    args_str = ""
            # Resolve current_state (needed for the 5-module formatters).
            # The state-machine object (if wired) gives us the live state;
            # otherwise we use the placeholder.
            current_state_for_prompt = self._get_current_state(character_id)
            user_message = build_user_prompt_5module(
                character_id=character_id,
                current_state=current_state_for_prompt,
                verb=verb,
                target=target,
                args_str=args_str,
                scene_context=scene_ctx or None,
            )

            # 6) Phase F3: read current state from the state machine.
            # If no state machine is wired, fall back to an empty
            # tag list — the F4 prompt builder will show
            # "(無當前狀態 — 健康)" so the LLM still has the section.
            current_state = self._get_current_state(character_id)

            # --- 故事套路系統與偏航發酵引擎實作 ---
            from backend.demo_mode import is_demo_mode
            
            # A. 加載資料庫中的 active_threads (非 demo 模式下)
            db_active_threads = {}
            if not is_demo_mode():
                try:
                    from backend.db import AsyncSessionLocal
                    from backend.models import CharacterState
                    from sqlalchemy import select
                    async with AsyncSessionLocal() as session:
                        stmt = select(CharacterState.active_threads).where(CharacterState.character_id == character_id)
                        result = await session.execute(stmt)
                        db_active_threads = result.scalar() or {}
                except Exception as e:
                    logger.warning(f"Failed to load active_threads from DB: {e}")
            
            # 同步給 current_state.active_threads
            if db_active_threads:
                current_state.active_threads = dict(db_active_threads)
            
            # B. 偏航發酵邏輯更新
            from backend.trope_router import TropeRouter
            router = TropeRouter()
            
            active_threads = getattr(current_state, "active_threads", {}) or {}
            active_tids = [tid for tid, data in active_threads.items() if data.get("status") in ("Active", "Evaded")]
            
            for tid in active_tids:
                tdata = active_threads[tid]
                trope_def = router.get_trope_by_id(tid)
                if not trope_def:
                    continue
                
                choice_fw = trope_def.get("choice_framework", {})
                req_verbs = choice_fw.get("required_verbs", [])
                
                # 判斷是否為偏航
                if verb in req_verbs:
                    # 面對衝突，套路完成
                    tdata["status"] = "Completed"
                else:
                    # 偏航/逃避
                    if tdata["status"] == "Active":
                        tdata["status"] = "Evaded"
                        tdata["escalation_level"] = 1
                    elif tdata["status"] == "Evaded":
                        tdata["escalation_level"] = tdata.get("escalation_level", 1) + 1
            
            # C. 套路分配器 (Trope Router)
            # 若當前沒有 active 的套路，嘗試觸發新套路
            still_active = [tid for tid, data in active_threads.items() if data.get("status") in ("Active", "Evaded")]
            if not still_active:
                # 收集匹配條件
                scene_type = "tavern"
                if scene_ctx and scene_ctx.get("location_tag"):
                    scene_type = scene_ctx["location_tag"]
                elif not is_demo_mode():
                    try:
                        from backend.db import AsyncSessionLocal
                        from backend.models import Scene
                        async with AsyncSessionLocal() as session:
                            sc = await session.get(Scene, scene_ctx.get("scene_id") or getattr(current_state, "current_scene_id", ""))
                            if sc and sc.location_tag:
                                scene_type = sc.location_tag
                    except Exception:
                        pass
                
                # 檢查其他已死角色痕跡
                has_other_player_trace = False
                if not is_demo_mode():
                    try:
                        from backend.db import AsyncSessionLocal
                        from backend.models import CharacterState
                        from sqlalchemy import select
                        async with AsyncSessionLocal() as session:
                            stmt = select(CharacterState).where(
                                CharacterState.world_id == getattr(current_state, "world_id", "world_default"),
                                CharacterState.character_id != character_id,
                                CharacterState.is_alive == False,
                                CharacterState.current_scene_id == getattr(current_state, "current_scene_id", "")
                            )
                            res = await session.execute(stmt)
                            if res.scalars().first() is not None:
                                has_other_player_trace = True
                    except Exception:
                        pass
                else:
                    # demo/測試模式下，可透過 args 或是 state 傳入 has_other_player_trace 模擬
                    if args and args.get("has_other_player_trace"):
                        has_other_player_trace = True
                
                npc_status = args.get("npc_status", "hostile_or_searching") if args else "hostile_or_searching"
                
                matched = router.find_matching_trope(scene_type, has_other_player_trace, npc_status)
                if matched:
                    current_state.active_threads[matched["trope_id"]] = {
                        "status": "Active",
                        "escalation_level": 0,
                        "seeded_round": 1,
                        "meta": {
                            "evade_consequence": matched.get("choice_framework", {}).get("evade_consequence", "")
                        }
                    }
            
            # D. 保存更新後的 active_threads 到資料庫 (非 demo 模式下)
            if not is_demo_mode():
                try:
                    from backend.db import engine
                    from sqlalchemy import text as _sql_text
                    import json as _json
                    async with engine.begin() as conn:
                        await conn.execute(
                            _sql_text(
                                "UPDATE character_states SET active_threads = CAST(:threads AS jsonb), "
                                "updated_at = now() WHERE character_id = :cid"
                            ),
                            {
                                "threads": _json.dumps(current_state.active_threads, ensure_ascii=False),
                                "cid": character_id,
                            }
                        )
                except Exception as e:
                    logger.warning(f"Failed to persist active_threads to DB: {e}")
            # --- 故事套路系統與偏航發酵引擎實作結束 ---

            # 7) Phase F3: build the system prompt via PromptBuilder.
            # This is where the F4 invariant lives: the current
            # state is ALWAYS at the top of the system prompt,
            # regardless of Memory Palace retrieval results.
            system_prompt = await self._build_system_prompt(
                character_id=character_id,
                current_state=current_state,
                verb=verb,
                target=target,
                args=args,
            )

            # 8) Phase F3 + G1: call the LLM with the StateMutation
            # contract. If the LLM does not support the new method
            # (e.g. a custom test double), fall back to the legacy
            # ``generate()`` path. ``max_retries`` is passed through
            # so the LLM can self-correct on a dropped mutation.
            llm_result = await self._call_llm_with_state_contract(
                system_prompt=system_prompt,
                user_message=user_message,
                current_state=current_state,
                max_retries=max_retries,
            )
            # Unpack 4-tuple OR 5-tuple (backward-compat)
            if len(llm_result) == 5:
                narrative, mutation, mutation_error, llm_elapsed_ms, llm_meta = llm_result
            else:
                narrative, mutation, mutation_error, llm_elapsed_ms = llm_result
                llm_meta = {}
            side_effects.append(
                {
                    "type": "llm_call",
                    "elapsed_ms": llm_elapsed_ms,
                    "verb": verb,
                    "state_contract": self._llm_supports_state_contract,
                    "choices": llm_meta.get("choices", []),
                }
            )
            # Phase G1: log ghost-state warnings so the ops side can
            # see when the LLM failed to produce a valid mutation
            # even after retries. The narrative is still returned
            # (F3 atomicity), but the player's state has diverged
            # from the narrative — observability is the only
            # remediation we can apply in-band.
            if llm_meta.get("ghost_state_warning"):
                retries_used = llm_meta.get("retries_used", 0)
                logger.warning(
                    "GHOST STATE (character=%s verb=%s): LLM failed "
                    "to produce a valid StateMutation after %d retries "
                    "(%s); narrative still returned, state unchanged. "
                    "last_error=%r",
                    character_id,
                    verb,
                    retries_used,
                    "max_retries exhausted"
                    if max_retries is not None
                    else "default retries exhausted",
                    mutation_error,
                )
                side_effects.append(
                    {
                        "type": "ghost_state_warning",
                        "retries_used": retries_used,
                        "last_error": (mutation_error or "")[:200],
                    }
                )

            # 9) Phase F3: apply the validated mutation (if any).
            # ``apply_mutations`` is atomic per-mutation: a bad
            # mutation in a list is dropped without affecting the
            # others. We pass a single-item list here.
            if mutation is not None and self._state_machine is not None:
                try:
                    apply_report = self._state_machine.apply_mutations([mutation])
                    side_effects.append(
                        {
                            "type": "state_mutation_applied",
                            "character_id": character_id,
                            "applied_count": len(apply_report.get("applied", [])),
                        }
                    )
                except Exception as exc:  # noqa: BLE001 — defensive
                    logger.warning(
                        "apply_mutations failed (non-fatal) for " "character=%s action=%s: %s",
                        character_id,
                        action_id,
                        exc,
                    )
                    side_effects.append(
                        {
                            "type": "state_mutation_apply_failed",
                            "error": str(exc)[:200],
                        }
                    )

            # 10) Phase F3: feed Memory Palace with the state-
            # anchored summary. This is the F1 defense D3 path:
            # the feed uses ``state=<tags>;narrative=<truncated>``
            # with a 127-char cap, so the vector store is not
            # polluted with raw narrative.
            if self._state_machine is not None:
                try:
                    # Refresh current_state to capture any applied
                    # mutation (so the feed reflects the post-mutation
                    # state, not the pre-mutation one).
                    post_state = self._get_current_state(character_id)
                    feed_id = await self._state_machine.feed_memory_palace(
                        character_id=character_id,
                        narrative=narrative,
                        current_state=post_state,
                    )
                    if feed_id is not None:
                        side_effects.append({"type": "memory_fed", "feed_id": feed_id})
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "feed_memory_palace failed (non-fatal) for " "character=%s action=%s: %s",
                        character_id,
                        action_id,
                        exc,
                    )
                    side_effects.append(
                        {
                            "type": "memory_feed_failed",
                            "error": str(exc)[:200],
                        }
                    )

            # 11) Legacy E1 path: also persist via the memory
            # palace's ``remember()`` if it is wired and not
            # already covered by the F3 feed above. This is a
            # no-op when the F3 path already produced a feed_id.
            if self.memory_palace is not None and not any(
                s.get("type") == "memory_fed" for s in side_effects
            ):
                try:
                    # We don't await with strict ordering — a failed
                    # persist must not block the HTTP response. The
                    # caller logs the memory id; failures are logged
                    # but don't surface.
                    memory_id = await self._persist_memory(
                        character_id=character_id,
                        verb=verb,
                        target=target,
                        narrative=narrative,
                        action_id=action_id,
                    )
                    if memory_id is not None:
                        side_effects.append({"type": "memory_persisted", "memory_id": memory_id})
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Memory persist failed (non-fatal) for " "character=%s action=%s: %s",
                        character_id,
                        action_id,
                        exc,
                    )
                    side_effects.append({"type": "memory_persist_failed", "error": str(exc)[:200]})

            # 12) Build the response.
            if mutation is not None:
                # Pydantic models support ``model_dump()``; if the
                # mutation is already a dict (older callers), use
                # it as-is.
                if hasattr(mutation, "model_dump"):
                    mutation_dict = mutation.model_dump()
                elif isinstance(mutation, dict):
                    mutation_dict = mutation
                else:
                    mutation_dict = {
                        "character_id": getattr(mutation, "character_id", ""),
                        "add_state": getattr(mutation, "add_state", []),
                        "remove_state": getattr(mutation, "remove_state", []),
                        "reason": getattr(mutation, "reason", ""),
                    }
            return {
                "status": "processed",
                "action_id": action_id,
                "narrative": narrative,
                "side_effects": side_effects,
                "received": {
                    "character_id": character_id,
                    "verb": verb,
                    "target": target,
                    "args": args or {},
                },
                "mutation": mutation_dict,
                "mutation_error": mutation_error,
                # 2026-06-08: 5-module user prompt asks for 4 follow-up
                # choices. Frontend uses these to render the
                # ChoiceCard. The choices are NOT state-changing; the
                # player's actual next action still goes through the
                # state machine + physics lock.
                "choices": llm_meta.get("choices", []),
            }
        finally:
            # 13) Always release the turn slot.
            await self.turn_system.end(character_id, action_id)

    async def _get_character_lock(self, character_id: str) -> asyncio.Lock:
        """Lazy per-character asyncio lock (physics-lock surrogate)."""
        async with self._locks_meta_lock:
            lock = self._character_locks.get(character_id)
            if lock is None:
                lock = asyncio.Lock()
                self._character_locks[character_id] = lock
            return lock

    # ---------------------- Phase F3 helpers ----------------------

    def _get_current_state(self, character_id: str) -> Any:
        """Read the character's current semantic state.

        Returns a :class:`backend.state_machine.SemanticState` (or a
        duck-typed equivalent) from the wired state machine. If no
        state machine is wired, returns a freshly-constructed empty
        ``SemanticState`` so the F4 prompt builder's "empty state"
        code path runs.

        This is a **synchronous** read (the state machine is in-memory
        in the test path; the production wire-up is also synchronous
        via the in-process dict).
        """
        if self._state_machine is None:
            # Lazy import to avoid pulling the state machine at
            # module-load time (it would create an import cycle for
            # the legacy E1 callers that don't need it).
            from backend.state_machine import SemanticState

            return SemanticState(character_id=character_id)
        # The state machine exposes a get_or_create helper.
        get = getattr(self._state_machine, "get_or_create", None)
        if callable(get):
            return get(character_id)
        get2 = getattr(self._state_machine, "get", None)
        if callable(get2):
            existing = get2(character_id)
            if existing is not None:
                return existing
        # Fallback: a fresh empty state.
        from backend.state_machine import SemanticState

        return SemanticState(character_id=character_id)

    async def _build_system_prompt(
        self,
        character_id: str,
        current_state: Any,
        verb: str,
        target: str | None,
        args: dict[str, Any] | None,
    ) -> str:
        """Build the system prompt via PromptBuilder (F4).

        Falls back to a small inline template if no prompt builder is
        wired. The fallback preserves the F4 invariant: the state
        section is at the top of the data, even when the builder is
        absent.
        """
        action_context: dict[str, Any] = {
            "verb": verb,
            "target": target or "(nothing)",
            "args": args or {},
        }
        if self._prompt_builder is not None:
            try:
                return await self._prompt_builder.build(
                    character_id=character_id,
                    current_state=current_state,
                    action_context=action_context,
                )
            except Exception as exc:  # noqa: BLE001 — defensive
                logger.warning(
                    "PromptBuilder.build() failed (non-fatal) for "
                    "character=%s: %s; using fallback prompt",
                    character_id,
                    exc,
                )
        # Fallback: a minimal system prompt with the state at the
        # top. Preserves the F4 "state is always at the top" rule.
        tags = getattr(current_state, "tags", []) or []
        if tags:
            state_str = " | ".join(f"「{t}」" for t in tags)
        else:
            state_str = "(無當前狀態 — 健康)"
        return (
            "你是一個文字冒險遊戲的 AI 主持人。\n\n"
            "# 角色當前狀態\n"
            f"{state_str}\n\n"
            "# 輸出格式要求\n"
            '- 輸出 JSON：{"narrative": "<narrative>", '
            '"state_mutations": <object> | null}\n'
        )

    async def _call_llm_with_state_contract(
        self,
        system_prompt: str,
        user_message: str,
        current_state: Any,
        max_retries: int | None = None,
    ) -> tuple:
        """Call the LLM with the F3 state contract.

        Returns a 4-tuple ``(narrative, mutation, mutation_error,
        elapsed_ms)``:

          * ``narrative`` — the LLM's narrative (always populated;
            falls back to a default string if the LLM returns an
            empty one).
          * ``mutation`` — the validated ``StateMutation`` instance
            (or ``None``).
          * ``mutation_error`` — short string if the mutation was
            rejected (or ``None``).
          * ``elapsed_ms`` — wall-clock time of the LLM call.

        If the LLM does not implement ``generate_with_state_contract``
        (legacy test double), falls back to the E1 ``generate()``
        path: returns ``(narrative, None, "state_contract_not_supported",
        elapsed_ms)``.
        """
        t0 = time.monotonic()
        if not self._llm_supports_state_contract:
            # Legacy path: call ``generate()`` and return a narrative
            # without a mutation. The processor still completes the
            # turn, but the state is not updated.
            try:
                raw = await self.llm_client.generate(
                    system_prompt=system_prompt,
                    user_message=user_message,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "LLM generate() failed (legacy path) for system=%r",
                    system_prompt[:60],
                )
                raise LLMUnavailableError(f"LLM unavailable: {type(exc).__name__}: {exc}") from exc
            narrative = (raw or "").strip() or ("你環顧四周，但沒有發生什麼特別的事。")
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return narrative, None, "state_contract_not_supported", elapsed_ms, {"choices": []}

        # F3 path: call the state-contract method on the LLM.
        tags = list(getattr(current_state, "tags", []) or [])
        try:
            result = await self.llm_client.generate_with_state_contract(
                system_prompt=system_prompt,
                user_message=user_message,
                current_state=tags,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "LLM generate_with_state_contract() failed for system=%r",
                system_prompt[:60],
            )
            raise LLMUnavailableError(f"LLM unavailable: {type(exc).__name__}: {exc}") from exc

        narrative = (result.get("narrative") or "").strip() or (
            "你環顧四周，但沒有發生什麼特別的事。"
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        # 2026-06-08: extract choices array from LLM result. The 5-module
        # user prompt asks for 4 follow-up options with direction +
        # vignette. Choices are NOT validated by R1 audit (they are
        # advisory UI suggestions; the player's actual next action is
        # still validated by the state machine + physics lock).
        choices = _validate_and_extract_choices(result.get("choices"))
        llm_meta = {
            "choices": choices,
            "ghost_state_warning": bool(result.get("ghost_state_warning", False)),
            "retries_used": int(result.get("retries_used", 0)),
        }
        return (
            narrative,
            result.get("mutation"),
            result.get("error"),
            elapsed_ms,
            llm_meta,
        )

    async def _persist_memory(
        self,
        character_id: str,
        verb: str,
        target: str | None,
        narrative: str,
        action_id: str,
    ) -> str | None:
        """Persist a one-line summary to Memory Palace. Best-effort.

        Returns the new memory_id on success, None on skip (no
        embedding-fn / not configured). Raises on hard failure.
        """
        palace = self.memory_palace
        if palace is None:
            return None

        # We don't have a real embedding model in the test path; the
        # integration endpoint's ``remember()`` requires a length-128
        # vector. We zero-fill if no embedding-fn is registered, which
        # is safe for test / demo — the palace will store the row and
        # the vector will simply have zero similarity. Production
        # wire-up would inject a real embedder via the constructor.
        from backend.memory_palace import EMBEDDING_DIM  # local import

        content = f"{verb} {target or ''}: {narrative}".strip()
        try:
            memory_id = await palace.remember(
                character_id=character_id,
                content=content[:1000],  # truncate for safety
                embedding=[0.0] * EMBEDDING_DIM,
                memory_type="episodic",
                salience=0.5,
                metadata={
                    "source": "action_processor",
                    "action_id": action_id,
                    "verb": verb,
                    "target": target or "",
                },
            )
            return memory_id
        except Exception:
            # Re-raise so the caller can record a side-effect.
            raise


# ============================================
# Factory — production wire-up
# ============================================


def build_default_processor() -> ActionProcessor:
    """Build the production ``ActionProcessor``.

    Uses ``get_llm_client()`` (env-driven, ``MockLLMClient`` by
    default) and an ``InMemoryTurnSystem`` for the turn gate. The
    Memory Palace integration is wired *lazily* by the FastAPI
    dependency on the memory-router endpoint; we pass ``None`` here
    so this module stays free of Postgres imports.

    Phase F3 also wires a fresh ``SemanticStateMachine`` and
    ``PromptBuilder`` (no memory palace yet — the builder falls
    back to its placeholder string). This makes the F3 contract
    live in production; the legacy E1 path is still selectable by
    passing ``state_machine=None`` and ``prompt_builder=None``.
    """
    # Local import keeps this module cheap to import in tests.
    from backend.llm_client import get_llm_client
    from backend.prompt_builder import PromptBuilder
    from backend.state_machine import SemanticStateMachine

    return ActionProcessor(
        llm_client=get_llm_client(),
        memory_palace=None,
        turn_system=InMemoryTurnSystem(),
        state_machine=SemanticStateMachine(),
        prompt_builder=PromptBuilder(memory_palace=None),
    )


__all__ = [
    "ActionProcessor",
    "ActionProcessorError",
    "LLMUnavailableError",
    "ProcessActionRequest",
    "ProcessActionResponse",
    "InMemoryTurnSystem",
    "ALLOWED_VERBS",
    "build_default_processor",
]
