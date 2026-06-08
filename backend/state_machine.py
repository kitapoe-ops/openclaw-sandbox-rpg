"""
Semantic State Machine (Phase F1-wide, 2026-06-05)
====================================================

Replaces the legacy numerical state machine (v3.7) with a **pure-text
semantic state** design. The new contract:

  * State is a list of short tags (max 7 tags added per mutation,
    max 15 chars per tag, CJK-only).
  * The LLM produces a `state_mutations` block describing what
    changed; the state machine applies it deterministically.
  * Physics Lock is an async, fail-closed, R1-audited call with a
    sync cache for repeated `(state, action)` pairs.
  * Memory Palace is fed with **tag concatenation**, not free-form
    narrative, to prevent vector pollution.

This is a freeze-and-replace of the legacy `CharacterStateMachine`
(which carried numerical thinking via `_tag_priorities` and
`stamina_level` / `health_status` enums). The 19 legacy tests in
`test_state_machine_tier1.py` are **deleted**; their semantic
invariants (catalogued in `docs/PHASE_F1_AUDIT.md`) are preserved as
the 15 test cases in `test_state_machine_semantic.py`.

`PhysicsLock` is folded into this module because the Physics Lock
*is* part of the state machine (it gates actions on state). For
backward compatibility with frozen callers (`backend.choice_validator`
imports `from .physics_lock import PhysicsLock`), a one-line re-export
is kept in `backend.physics_lock`. This is **not a migration shim**:
it is the same class, same constructor, same methods, just defined
in this module. See `docs/PHASE_F1_SUMMARY.md` for the rationale.

3 Critical Defenses (user-flagged architectural risks)
------------------------------------------------------
D1 — Physics Lock Performance
    `is_action_allowed` is async, R1-audited, sync-cached, and
    fail-closed on timeout (default 5s). The cache key is
    `(frozenset(state_tags), action_text)`; hits return in <1ms.

D2 — JSON Schema Strict Validation
    `StateMutation` is Pydantic strict (`extra="forbid"`, strict
    mode). `add_state` / `remove_state` are bounded (max 7 items,
    each max 15 chars, CJK-only via regex). A single invalid
    field drops the WHOLE mutation (atomicity).

D3 — Memory Palace Vector Pollution
    State is `list[str]`, not paragraphs. Memory feed uses
    `;`-joined tags (≤127 chars) as the primary anchor, not
    narrative. Duplicate tags (fuzzy match >0.85) are rejected
    to prevent vector pollution.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


# ============================================
# Constants
# ============================================

# Max tags a character can hold simultaneously. The 8 comes from the
# audit's preserved invariant #5 ("bounded tag budget"); the exact
# number is incidental but matches the legacy contract.
MAX_TAGS_PER_CHARACTER: int = 8

# Max tags a single StateMutation can add/remove (defense D2 + audit
# recommendation). 7 keeps a 1-tag headroom under the 8-char cap.
MAX_TAGS_PER_MUTATION: int = 7

# Max chars per tag. Short tags = clean vector embeddings, no
# narrative pollution. Matches audit §3 category D recommendation.
MAX_TAG_LENGTH: int = 15

# CJK + Hiragana + Katakana + space + hyphen. No punctuation, no
# emoji, no Latin. Audit invariant #1 ("status tags are short CJK
# descriptors") is enforced here.
_TAG_PATTERN = re.compile(r"^[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\- ]+$")

# Cap on the memory feed string (defense D3). 127 chars to fit in a
# short TEXT column on every backend and stay under typical
# embedding model token limits.
MAX_MEMORY_FEED_LENGTH: int = 127

# Default Physics Lock R1 audit timeout. 5s is the maximum time the
# FastAPI main thread will block on an audit before the action is
# rejected (defense D1 — fail-closed).
DEFAULT_PHYSICS_LOCK_TIMEOUT_S: float = 5.0

# Default fuzzy-match threshold for duplicate tag rejection (defense D3).
# Tags with cosine similarity > 0.85 to an existing tag are rejected.
DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD: float = 0.85


# ============================================
# Errors
# ============================================


class StateMachineError(Exception):
    """Base for semantic state machine errors."""


class PhysicsLockTimeoutError(StateMachineError):
    """R1 audit timed out (defense D1). Action must be rejected."""


class StateValidationError(StateMachineError):
    """A StateMutation failed Pydantic validation (defense D2)."""


# ============================================
# Pydantic Models (Defense D2)
# ============================================


def _validate_tag(tag: str) -> str:
    """Validate a single tag against D2 rules: non-empty, ≤15 chars, CJK-only."""
    if not isinstance(tag, str):
        raise ValueError(f"tag must be str, got {type(tag).__name__}")
    if not tag.strip():
        raise ValueError("tag is empty or whitespace-only")
    if len(tag) > MAX_TAG_LENGTH:
        raise ValueError(f"tag too long: {len(tag)} > {MAX_TAG_LENGTH} chars ({tag!r})")
    if not _TAG_PATTERN.match(tag):
        raise ValueError(f"invalid characters in tag (only CJK + space + hyphen allowed): {tag!r}")
    return tag


class ItemConsumed(BaseModel):
    """One item consumption record inside a StateMutation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    item_id: str = Field(..., min_length=1, max_length=64)
    quantity: int = Field(..., ge=1, le=999)


class RelationshipChange(BaseModel):
    """One relationship update inside a StateMutation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    npc_id: str = Field(..., min_length=1, max_length=64)
    new_relationship: str = Field(..., min_length=1, max_length=64)


class StateMutation(BaseModel):
    """One atomic state change. The whole mutation is dropped if any
    field fails Pydantic validation (defense D2 — atomicity).

    LLM-facing contract: this is what the scene agent emits in its
    `state_mutations` JSON block. Fields are optional; emit only the
    ones that actually changed. The `reason` is required for
    narrative grounding (audit invariant #16).
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    # Who is being mutated. Either "self" (the action's actor) or
    # an explicit character_id (for NPC-targeted mutations).
    target: Literal["self", "other"] = "self"
    character_id: str = Field(..., min_length=1, max_length=64)

    # Pure-text tag mutations (defense D2: max 7, each max 15 chars).
    add_state: list[str] = Field(default_factory=list, max_length=MAX_TAGS_PER_MUTATION)
    remove_state: list[str] = Field(default_factory=list, max_length=MAX_TAGS_PER_MUTATION)

    # Optional scalar state changes. All strings, no numbers (no more
    # stamina_level / health_status enums; the LLM picks the
    # descriptor, the audit pins the convention).
    stamina: str | None = Field(default=None, max_length=64)
    health: str | None = Field(default=None, max_length=64)
    morale: str | None = Field(default=None, max_length=64)

    # Side effects (defense D2: bounded lists).
    items_consumed: list[ItemConsumed] = Field(default_factory=list, max_length=16)
    new_memories: list[str] = Field(default_factory=list, max_length=16)
    relationship_changes: list[RelationshipChange] = Field(default_factory=list, max_length=16)

    # Narrative grounding (audit invariant #16).
    reason: str = Field(..., min_length=1, max_length=200)

    @field_validator("add_state", "remove_state", mode="after")
    @classmethod
    def _validate_tag_list(cls, tags: list[str]) -> list[str]:
        """Apply D2 tag-level validation to every item in the list.

        Raises ValueError on the first invalid tag — the WHOLE
        StateMutation is then rejected by Pydantic (atomicity).
        """
        for tag in tags:
            _validate_tag(tag)
        return tags

    @field_validator("new_memories", mode="after")
    @classmethod
    def _validate_memory_lengths(cls, memories: list[str]) -> list[str]:
        for mem in memories:
            if not isinstance(mem, str) or not mem.strip():
                raise ValueError(f"memory is empty or non-str: {mem!r}")
            if len(mem) > 500:
                raise ValueError(f"memory too long: {len(mem)} > 500 chars")
        return memories


# ============================================
# Physics Lock rules (default)
# ============================================
# These are the legacy rules from `backend/physics_lock.py` (v2.0).
# The new state machine keeps the same default rule map; future
# worlds can override via physics_lock_rules.yaml (deferred to F2).

DEFAULT_FORBIDDEN_ACTIONS: dict[str, list[str]] = {
    "雙腿嚴重骨折": ["狂奔", "跳躍", "攀爬", "衝刺", "疾跑"],
    "左臂骨折": ["雙手握劍", "投擲", "格擋"],
    "右臂骨折": ["雙手握劍", "寫字", "投擲"],
    "雙臂骨折": ["擁抱", "格擋", "投擲", "握手"],
    "失明": ["觀察", "瞄準", "閱讀", "搜索"],
    "聾啞": ["聆聽", "呼叫", "對話"],
    "中毒": ["劇烈運動", "戰鬥"],
    "暈眩": ["瞄準", "精細操作"],
}


# ============================================
# PhysicsLock
# ============================================


class PhysicsLock:
    """Validates player actions against semantic state.

    Defense D1: This class is **async**, **R1-audited**, **fail-closed**,
    and **sync-cached**. See `SemanticStateMachine.is_action_allowed`
    for the high-level entry point; `PhysicsLock.validate` is the
    sync fast-path (no R1 call) used for in-process validation.

    The async R1 path is what gates user-facing actions in the demo;
    the sync path is what the LLM uses to self-check before emitting
    a `state_mutations` block (cheaper, no audit round-trip).
    """

    def __init__(
        self,
        custom_rules: dict[str, list[str]] | None = None,
        audit_queue: Any = None,
        r1_prompt_builder: Callable[[str, list[str]], str] | None = None,
        timeout_s: float = DEFAULT_PHYSICS_LOCK_TIMEOUT_S,
    ) -> None:
        self.rules: dict[str, list[str]] = {**DEFAULT_FORBIDDEN_ACTIONS}
        if custom_rules:
            self.rules.update(custom_rules)
        self._audit_queue = audit_queue
        self._r1_prompt_builder = r1_prompt_builder or self._default_prompt
        self._timeout_s = timeout_s
        # Sync cache: cache_key -> (allowed: bool, reason: str).
        # Keyed by (frozenset(state_tags), action_text).
        self._cache: dict[tuple[frozenset[str], str], dict[str, Any]] = {}
        # Track audit latency for the cache (debug / observability).
        self._audit_call_count: int = 0
        self._audit_cache_hits: int = 0

    # -------- sync path (in-process, no R1) --------

    def validate(
        self,
        action_text: str,
        state_tags: list[str],
    ) -> dict[str, Any]:
        """Synchronous validation. Returns {"allowed": bool, "reason": str}.

        This is the fast path used for LLM self-check and for tests.
        It is **not** the user-facing gate — that is
        `SemanticStateMachine.is_action_allowed` (async, R1-audited).
        """
        for tag in state_tags:
            if tag in self.rules:
                forbidden = self.rules[tag]
                for action in forbidden:
                    if action in action_text:
                        return {
                            "allowed": False,
                            "reason": f"Effect '{tag}' forbids action '{action}'",
                        }
        return {"allowed": True, "reason": "ok"}

    # -------- async path (R1 audit, fail-closed, cached) --------

    async def is_action_allowed(
        self,
        character_id: str,
        action_text: str,
        state_tags: list[str],
    ) -> dict[str, Any]:
        """Async, R1-audited, fail-closed physics-lock check.

        Defense D1 implementation:

          1. Cache lookup by (frozenset(state_tags), action_text).
             Hit → return in <1ms.
          2. Submit to `audit_queue` (if wired) with a 5s wall-clock
             budget. R1 verdict is the source of truth.
          3. On timeout / unparseable response / uncaught error →
             FAIL-CLOSED with reason `R1_audit_timeout_fail_closed`.
          4. Cache the result. Subsequent calls with the same key
             return synchronously.

        Returns `{"allowed": bool, "reason": str}`.

        `reason` is one of:
          - "ok" — R1 said PASS or CONDITIONAL, or sync fast-path allowed
          - "R1_audit_timeout_fail_closed" — timeout / unparseable / error
          - "Effect 'X' forbids action 'Y'" — sync fast-path rejection
          - The first finding's `issue` field — R1 explicit failure
        """
        cache_key = (frozenset(state_tags), action_text)
        if cache_key in self._cache:
            self._audit_cache_hits += 1
            return self._cache[cache_key]

        # Sync fast-path first — if a hard rule rejects, no need to
        # waste an R1 round-trip. This is the same logic as `validate`.
        sync_result = self.validate(action_text, state_tags)
        if not sync_result["allowed"]:
            self._cache[cache_key] = sync_result
            return sync_result

        # No audit queue wired → treat as allowed (sync-only mode).
        # This is the case in tests and in the F1 minimum-viable
        # demo before R1 is hooked up. Production must wire an
        # audit_queue.
        if self._audit_queue is None:
            self._cache[cache_key] = sync_result
            return sync_result

        # Async R1 audit with fail-closed timeout.
        prompt = self._r1_prompt_builder(action_text, list(state_tags))
        try:
            request_id = await asyncio.wait_for(
                self._audit_queue.submit(
                    _build_audit_request(character_id, action_text, state_tags, prompt)
                ),
                timeout=self._timeout_s,
            )
            result = await asyncio.wait_for(
                self._audit_queue.get_result(request_id, timeout=self._timeout_s),
                timeout=self._timeout_s,
            )
            self._audit_call_count += 1
        except TimeoutError:
            logger.warning(
                "physics_lock: R1 audit timed out for character=%s action=%r",
                character_id,
                action_text[:40],
            )
            response = {
                "allowed": False,
                "reason": "R1_audit_timeout_fail_closed",
            }
            self._cache[cache_key] = response
            return response
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "physics_lock: R1 audit errored for character=%s: %s",
                character_id,
                exc,
            )
            response = {
                "allowed": False,
                "reason": "R1_audit_timeout_fail_closed",
            }
            self._cache[cache_key] = response
            return response

        # Map R1 verdict to allowed/reason.
        # PASS / CONDITIONAL → allowed; FAIL / ERROR / TIMEOUT → rejected.
        try:
            from backend.audit_queue import AuditVerdict  # local import to avoid cycle

            if result.verdict in (AuditVerdict.PASS, AuditVerdict.CONDITIONAL):
                response = {"allowed": True, "reason": "ok"}
            else:
                # FAIL / ERROR / TIMEOUT → reject with first finding's
                # issue (if any) or generic message.
                reason = "R1_audit_rejected"
                if result.findings:
                    issue = result.findings[0].get("issue")
                    if issue:
                        reason = str(issue)[:200]
                response = {"allowed": False, "reason": reason}
        except Exception as exc:  # noqa: BLE001
            logger.warning("physics_lock: failed to parse R1 result: %s", exc)
            response = {
                "allowed": False,
                "reason": "R1_audit_timeout_fail_closed",
            }

        self._cache[cache_key] = response
        return response

    def clear_cache(self) -> None:
        """Reset the sync cache. Useful between test cases."""
        self._cache.clear()
        self._audit_call_count = 0
        self._audit_cache_hits = 0

    @staticmethod
    def _default_prompt(action_text: str, state_tags: list[str]) -> str:
        return (
            f"Character state tags: {state_tags}\n"
            f"Proposed action: {action_text}\n"
            f"Is this action physically allowed? Reply PASS, CONDITIONAL, or FAIL."
        )


def _build_audit_request(
    character_id: str,
    action_text: str,
    state_tags: list[str],
    prompt: str,
) -> Any:
    """Build an AuditRequest for the physics lock check.

    Local import keeps `state_machine` importable without audit_queue
    (audit_queue imports nothing from state_machine, but the
    reverse is not true).
    """
    from backend.audit_queue import AuditRequest

    return AuditRequest(
        target_files=[f"characters/{character_id}.md"],
        concerns=[prompt],
        context={
            "character_id": character_id,
            "action_text": action_text,
            "state_tags": state_tags,
            "request_kind": "physics_lock",
        },
    )


# ============================================
# Semantic State
# ============================================


class SemanticState:
    """A character's current semantic state.

    Pure text: a list of short tags. No numbers, no nested enums.
    The list is the source of truth; the audit invariants (#5, #12,
    etc.) are enforced by the state machine, not by this class.

    Use `SemanticStateMachine.apply_mutations` to change a character's
    state; do NOT mutate this object in place.
    """

    __slots__ = (
        "character_id",
        "tags",
        "stamina",
        "health",
        "morale",
        "memories",
        "relationships",
        "inventory",
        "active_threads",
        "_updated_at",
    )

    def __init__(
        self,
        character_id: str,
        tags: list[str] | None = None,
        stamina: str | None = None,
        health: str | None = None,
        morale: str | None = None,
        memories: list[str] | None = None,
        relationships: dict[str, str] | None = None,
        inventory: dict[str, Any] | None = None,
        active_threads: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(character_id, str) or not character_id.strip():
            raise StateValidationError(f"character_id must be non-empty str, got {character_id!r}")
        # Validate tags on construction (defense D2: CJK + length).
        tags = tags or []
        for t in tags:
            try:
                _validate_tag(t)
            except ValueError as exc:
                raise StateValidationError(str(exc)) from exc
        if len(tags) > MAX_TAGS_PER_CHARACTER:
            raise StateValidationError(
                f"character {character_id!r} has {len(tags)} tags, "
                f"max is {MAX_TAGS_PER_CHARACTER}"
            )
        self.character_id = character_id
        self.tags: list[str] = list(tags)
        self.stamina = stamina
        self.health = health
        self.morale = morale
        self.memories: list[str] = list(memories or [])
        self.relationships: dict[str, str] = dict(relationships or {})
        self.inventory: dict[str, Any] = dict(inventory or {"items": []})
        self.active_threads: dict[str, Any] = dict(active_threads or {})
        self._updated_at: datetime = datetime.now(UTC)

    # -------- convenience --------

    def to_memory_string(self) -> str:
        """Defense D3: produce the memory-feed string from tags only.

        Concatenates tags with `;` separator; bounded to
        `MAX_MEMORY_FEED_LENGTH` chars. Returns "(no_state)" if the
        character has no tags.
        """
        if not self.tags:
            return "(no_state)"
        joined = ";".join(self.tags)
        return joined[:MAX_MEMORY_FEED_LENGTH]

    def updated_at(self) -> datetime:
        return self._updated_at

    def touch(self) -> None:
        """Bump updated_at. Called by the state machine on every apply."""
        self._updated_at = datetime.now(UTC)

    def __repr__(self) -> str:  # pragma: no cover — debug only
        return (
            f"SemanticState(character_id={self.character_id!r}, "
            f"tags={self.tags!r}, stamina={self.stamina!r}, "
            f"health={self.health!r}, morale={self.morale!r})"
        )


# ============================================
# Semantic State Machine
# ============================================


class SemanticStateMachine:
    """Pure-text semantic state machine. NO numerical fields.

    Replaces the legacy `CharacterStateMachine`. The 15 audit
    invariants are enforced as deterministic apply rules — no LLM
    judgment in the hot path, no priority side-channel, no
    `stamina_level` enum.

    Defense wiring:
      D1 → `is_action_allowed` (delegates to PhysicsLock)
      D2 → `apply_mutations` validates each `StateMutation` via
           Pydantic; the WHOLE mutation is dropped on any field error.
      D3 → `feed_memory_palace` uses `SemanticState.to_memory_string`
           (tag concatenation, bounded length).
    """

    def __init__(
        self,
        audit_queue: Any = None,
        memory_palace: Any = None,
        physics_lock: PhysicsLock | None = None,
        duplicate_similarity_threshold: float = DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD,
    ) -> None:
        self._audit_queue = audit_queue
        self._memory_palace = memory_palace
        self._physics_lock = physics_lock or PhysicsLock(audit_queue=audit_queue)
        self._duplicate_similarity_threshold = duplicate_similarity_threshold
        # In-memory state store. Production wire-up uses
        # `persistence_pg.py`; this dict is the test/demo source.
        self._states: dict[str, SemanticState] = {}

    # -------- state store --------

    def register(self, state: SemanticState) -> None:
        """Insert or replace a character's state. Test/demo helper."""
        if not isinstance(state, SemanticState):
            raise StateMachineError(
                f"register() requires SemanticState, got {type(state).__name__}"
            )
        self._states[state.character_id] = state

    def get(self, character_id: str) -> SemanticState | None:
        return self._states.get(character_id)

    def get_or_create(self, character_id: str) -> SemanticState:
        state = self._states.get(character_id)
        if state is None:
            state = SemanticState(character_id=character_id)
            self._states[character_id] = state
        return state

    # -------- audit invariants 1, 2, 3, 4, 5 (tag mutations) --------

    def _apply_tag_mutation(
        self,
        state: SemanticState,
        add: list[str],
        remove: list[str],
    ) -> dict[str, Any]:
        """Apply add/remove with capacity enforcement (invariant #5).

        Returns a side-effect report dict for the caller's
        side_effects list. The state object is mutated in place.

        Invariants preserved:
          #1 — add_state adds a tag to `active_effects`
          #2 — remove_state removes a tag from `active_effects`
          #3 — remove_state on a missing tag is a silent no-op
          #4 — re-adding an existing tag is idempotent (no duplicate)
          #5 — max 8 tags; lowest-priority (lexicographic) is evicted
        """
        report = {"added": [], "removed": [], "evicted": []}

        # Remove first (invariant #3: silent no-op on missing).
        for tag in remove:
            if tag in state.tags:
                state.tags.remove(tag)
                report["removed"].append(tag)

        # Add (with capacity enforcement).
        for tag in add:
            if tag in state.tags:
                # Invariant #4: idempotent re-add. Skip but don't fail.
                continue
            # Defense D3: reject duplicate / overly-similar tags.
            if self._is_duplicate_tag(tag, state.tags):
                report.setdefault("rejected_duplicates", []).append(tag)
                continue
            if len(state.tags) >= MAX_TAGS_PER_CHARACTER:
                # Invariant #5: evict the lowest-priority (lexicographic
                # last) tag. Deterministic, no LLM judgment.
                evict_target = max(state.tags)
                state.tags.remove(evict_target)
                report["evicted"].append(evict_target)
            state.tags.append(tag)
            report["added"].append(tag)

        return report

    def _is_duplicate_tag(self, candidate: str, existing: list[str]) -> bool:
        """Defense D3: reject a tag that fuzzy-matches an existing one.

        Default comparison is character-level Jaccard similarity
        (proxy for "would produce a near-identical vector embedding").
        A real cosine-similarity implementation requires an embedding
        model; this proxy is sufficient for the F1 test suite and
        preserves the contract: "tags that are 85%+ similar are
        treated as duplicates".
        """
        if not existing:
            return False
        cand_set = set(candidate)
        for tag in existing:
            tag_set = set(tag)
            union = cand_set | tag_set
            if not union:
                continue
            jaccard = len(cand_set & tag_set) / len(union)
            if jaccard >= self._duplicate_similarity_threshold:
                return True
        return False

    # -------- audit invariants 6, 7, 8 (scalar state) --------

    def _apply_scalar_mutation(
        self,
        state: SemanticState,
        stamina: str | None,
        health: str | None,
        morale: str | None,
    ) -> dict[str, Any]:
        """Apply scalar state changes (invariants #6, #7, #8).

        All values are strings (no numbers). The LLM picks the
        descriptor; the audit pins the convention.
        """
        report = {}
        if stamina is not None:
            state.stamina = stamina
            report["stamina"] = stamina
        if health is not None:
            state.health = health
            report["health"] = health
        if morale is not None:
            state.morale = morale
            report["morale"] = morale
        return report

    # -------- audit invariants 9, 10, 11 (items) --------

    def _apply_items_consumed(
        self,
        state: SemanticState,
        items_consumed: list[ItemConsumed],
    ) -> dict[str, Any]:
        """Apply item consumption (invariants #9, #10, #11).

        #9  — quantity is decremented; partially-consumed items persist
        #10 — quantity == 0 ⇒ item is removed from inventory
        #11 — unknown item IDs are a silent no-op
        """
        items = state.inventory.setdefault("items", [])
        report = {"consumed": [], "removed": [], "unknown": []}
        for consumed in items_consumed:
            item_id = consumed.item_id
            qty = consumed.quantity
            matched = False
            for item in items:
                if item.get("item_id") == item_id:
                    current = item.get("quantity", 0)
                    item["quantity"] = max(0, current - qty)
                    report["consumed"].append({"item_id": item_id, "quantity": qty})
                    if item["quantity"] == 0:
                        items.remove(item)
                        report["removed"].append(item_id)
                    matched = True
                    break
            if not matched:
                # Invariant #11: silent no-op.
                report["unknown"].append(item_id)
        return report

    # -------- audit invariants 12, 13 (memories) --------

    def _apply_new_memories(
        self,
        state: SemanticState,
        new_memories: list[str],
    ) -> dict[str, Any]:
        """Append new memories in input order (invariants #12, #13)."""
        if not new_memories:
            return {"appended": []}
        state.memories.extend(new_memories)
        return {"appended": list(new_memories)}

    # -------- audit invariant 14 (relationships) --------

    def _apply_relationship_changes(
        self,
        state: SemanticState,
        rel_changes: list[RelationshipChange],
    ) -> dict[str, Any]:
        """Update relationship map (invariant #14). No enum enforcement
        (audit finding #15 — defer to F2 or manual flag)."""
        report = []
        for change in rel_changes:
            state.relationships[change.npc_id] = change.new_relationship
            report.append({"npc_id": change.npc_id, "new": change.new_relationship})
        return {"updated": report}

    # -------- main entry point (audit invariants 6-16) --------

    def apply_mutations(
        self,
        mutations: list[StateMutation],
    ) -> dict[str, Any]:
        """Apply a list of StateMutations atomically (per-mutation).

        Per the brief: each mutation is applied as a unit. A mutation
        that fails Pydantic validation is dropped at the *Pydantic*
        layer (defense D2 — caller is expected to validate before
        calling). Once a mutation reaches this method, all its
        sub-effects (tag add/remove, scalar change, items, memories,
        relationships) are applied in one pass.

        Returns a side-effects report (one entry per applied
        mutation) and bumps `updated_at` on each affected character.

        Invariants preserved:
          #6, #7, #8 — stamina/health/morale applied verbatim
          #9, #10, #11 — item consumption accounting
          #12, #13 — memory append ordering
          #14 — relationship update
          #16 — reason field is preserved in the report
        """
        if not isinstance(mutations, list):
            raise StateMachineError(
                f"apply_mutations requires list[StateMutation], got {type(mutations).__name__}"
            )

        report = {
            "applied": [],
            "dropped": [],
            "side_effects_total": 0,
        }

        for mutation in mutations:
            if not isinstance(mutation, StateMutation):
                # Defense D2: an invalid mutation is dropped (not
                # partially applied). We don't raise here because the
                # caller's batch may contain good and bad mutations.
                report["dropped"].append({"reason": "not a StateMutation"})
                continue

            character_id = mutation.character_id
            state = self.get_or_create(character_id)
            effects: dict[str, Any] = {"character_id": character_id, "reason": mutation.reason}

            # Apply sub-effects in deterministic order.
            effects["tags"] = self._apply_tag_mutation(
                state, mutation.add_state, mutation.remove_state
            )
            effects["scalars"] = self._apply_scalar_mutation(
                state, mutation.stamina, mutation.health, mutation.morale
            )
            effects["items"] = self._apply_items_consumed(state, mutation.items_consumed)
            effects["memories"] = self._apply_new_memories(state, mutation.new_memories)
            effects["relationships"] = self._apply_relationship_changes(
                state, mutation.relationship_changes
            )

            state.touch()
            report["applied"].append(effects)
            report["side_effects_total"] += 1

        return report

    # -------- defense D1 --------

    async def is_action_allowed(
        self,
        character_id: str,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        """Physics Lock check. Defense D1.

        Returns `{"allowed": bool, "reason": str}`. Fails closed on
        R1 audit timeout / error. Caches results by (state, action).

        `action` is a dict; `action["text"]` (or `action["verb"] +
        " " + action.get("target", "")`) is the gated text.
        `action.get("current_state", [])` may override the stored
        state tags (useful for "what-if" checks).
        """
        action_text = self._action_to_text(action)
        if "current_state" in action and isinstance(action["current_state"], list):
            state_tags = list(action["current_state"])
        else:
            stored = self._states.get(character_id)
            state_tags = list(stored.tags) if stored else []
        return await self._physics_lock.is_action_allowed(
            character_id=character_id,
            action_text=action_text,
            state_tags=state_tags,
        )

    @staticmethod
    def _action_to_text(action: dict[str, Any]) -> str:
        """Extract the gate-able text from an action dict."""
        if "text" in action and action["text"]:
            return str(action["text"])
        verb = action.get("verb", "")
        target = action.get("target", "")
        return f"{verb} {target}".strip()

    # -------- defense D3 --------

    async def feed_memory_palace(
        self,
        character_id: str,
        narrative: str,
        current_state: SemanticState | None = None,
    ) -> str | None:
        """Feed Memory Palace. Defense D3.

        Concatenates tags (NOT narrative) as the primary anchor.
        The narrative is appended as secondary context, truncated to
        200 chars. The total feed is bounded to MAX_MEMORY_FEED_LENGTH
        (127 chars).
        """
        palace = self._memory_palace
        if palace is None:
            return None
        if current_state is None:
            current_state = self._states.get(character_id)
        if current_state is None:
            return None
        # D3: tag concatenation is the primary anchor.
        state_str = current_state.to_memory_string()
        # Narrative is secondary, truncated.
        narr_trunc = (narrative or "")[:200]
        # Build the feed string, bounded.
        feed = f"state={state_str};narrative={narr_trunc}"
        feed = feed[:MAX_MEMORY_FEED_LENGTH]
        try:
            # The palace's `remember` interface may vary; we look
            # for the most common one and fall back to no-op.
            if hasattr(palace, "remember"):
                rv = palace.remember(
                    character_id=character_id,
                    content=feed,
                )
                if asyncio.iscoroutine(rv):
                    return await rv
                return rv
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "feed_memory_palace failed for character=%s: %s",
                character_id,
                exc,
            )
            return None
        return None


# ============================================
# Backward-compat shim — DO NOT use in new code
# ============================================
#
# The legacy `CharacterStateMachine` class is **removed** in F1. It
# was numerical-thinking scaffolding; the 19 legacy tests are
# deleted along with it. New code MUST use `SemanticStateMachine`.
#
# If a frozen caller still references `CharacterStateMachine`, the
# import will raise ImportError — that is intentional, to surface
# the migration gap before F2 ships.


__all__ = [
    "DEFAULT_FORBIDDEN_ACTIONS",
    "DEFAULT_PHYSICS_LOCK_TIMEOUT_S",
    "DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD",
    "MAX_TAGS_PER_CHARACTER",
    "MAX_TAGS_PER_MUTATION",
    "MAX_TAG_LENGTH",
    "MAX_MEMORY_FEED_LENGTH",
    "ItemConsumed",
    "PhysicsLock",
    "PhysicsLockTimeoutError",
    "RelationshipChange",
    "SemanticState",
    "SemanticStateMachine",
    "StateMachineError",
    "StateMutation",
    "StateValidationError",
]
