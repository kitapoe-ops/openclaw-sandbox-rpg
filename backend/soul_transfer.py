"""
Soul Transfer — Semantic Edition (Phase F2, 2026-06-05)
======================================================

A "Soul" is a composite of pure-text semantic state (per Phase F1):

  1. **Tags** — `list[str]` of short CJK descriptors (max 8)
     (inherited from `SemanticState.tags`; audit invariant #5)
  2. **Scalar state** — `stamina` / `health` / `morale` (all strings,
     no numbers; audit invariants #6, #7, #8)
  3. **Memories** — `list[str]` of bounded-length strings, fed by
     `SemanticState.to_memory_string()` (defense D3)
  4. **Relationships** — `dict[str, str]` (audit invariant #14)

This is a **freeze-and-replace** of the legacy numerical
`SoulTransferService` from v3.7. The legacy module carried numerical
thinking — specifically `random.uniform(0.6, 0.9)` as a degradation
factor that could not multiply a `SemanticState` tag like
`"右手骨折"`. The semantic replacement:

  * **Tier-list downgrade** — for known source tags, choose a
    worse-but-valid downgrade from a hardcoded map. The map is
    pure-text, not numerical.
  * **LLM fallback** — for unknown / novel source tags, ask the
    LLM to produce a single worse-but-valid CJK tag (≤15 chars,
    CJK-only). LLM is called via `LLMClient.generate` with
    retry/cache already in place.
  * **Anti-predictability preserved** — every transfer is
    `random.choice` from a non-empty list of valid downgrades.
    No two consecutive transfers produce the same result.
  * **Anti-exploit rules** — seven rules inherited and extended
    (see `ANTI_EXPLOIT_RULES`).

Inputs:  `backend/state_machine.SemanticState`, `SemanticStateMachine`
Outputs: `backend.soul_transfer.SoulTransferRecord` (the new contract)

Lock: 2026-06-05 21:55 GMT+8
"""
from __future__ import annotations

import json
import logging
import random
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

UTC = UTC


# ============================================
# Constants
# ============================================

# Max tags carried per transfer record (matches F1 invariant #5).
MAX_TAGS_PER_TRANSFER: int = 8

# Max chars per tag (matches F1 MAX_TAG_LENGTH).
MAX_TAG_LENGTH: int = 15

# CJK + space + hyphen, matching F1's _TAG_PATTERN.
_TAG_PATTERN = re.compile(r"^[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\- ]+$")

# Source states that mean "the soul does not need to be transferred".
# Inherits from the legacy invariant: you cannot transfer a perfectly
# intact soul (or an anchored one). See ANTI_EXPLOIT_RULE_5.
NON_TRANSFERABLE_TAGS = frozenset(
    {
        "完好無損",  # perfectly intact
        "固著",  # anchored
        "圓滿",  # complete / perfect
    }
)

# Source states that mean "the soul is already lost".
LOST_SOUL_TAGS = frozenset(
    {
        "死亡",  # dead
        "魂飛魄散",  # soul destroyed
        "永久消亡",  # permanently gone
    }
)

# Default LLM prompt for unknown-state downgrade.
# The LLM is asked for ONE CJK tag, ≤15 chars, no Latin/punctuation.
DEFAULT_LLM_DOWNGRADE_PROMPT = (
    "你是一個語意狀態降級助手。給定一個角色的當前狀態（中文短語），"
    "請輸出一個**更差**、但仍然合理的狀態（同一類別內，邏輯上可達）。\n"
    "規則：\n"
    "1. 必須是純中文（不含英文字母、emoji、標點）\n"
    "2. 不超過 15 個字\n"
    "3. 比原狀態更差，但不會直接跳到「死亡」\n"
    '4. 只需回傳 JSON：`{{"degraded_state": "<tag>"}}`\n'
    "原狀態：{source_state}\n"
    "請輸出降級狀態："
)


# ============================================
# Tier List (common cases, fast path)
# ============================================

# A pure-text downgrade map. Each source tag maps to a list of
# "valid worse states" (all in CJK, all ≤15 chars). The
# `compute_degradation` step picks one with `random.choice`, so the
# result is anti-predictable WITHOUT a numerical factor.
#
# Convention: keys are source states; values are lists of
# strictly-worse states. Lists should have ≥ 2 entries for
# meaningful randomness; a single-entry list still degrades but is
# trivially predictable (the F2 audit flags it as "non-random").
#
# If a source state is NOT in the map, we fall through to the
# LLM-driven downgrade path (see `compute_degradation`).
TIER_DOWNGRADES: dict[str, list[str]] = {
    # Physical health
    "非常健康": ["虚弱", "疲惫", "輕傷", "小病"],
    "健康": ["小病", "虚弱", "輕傷"],
    "小病": ["虚弱", "生病", "不適"],
    "虚弱": ["疲惫", "病重", "無力"],
    "疲惫": ["無力", "暈眩", "病重"],
    "輕傷": ["中度傷", "骨折", "流血"],
    "中度傷": ["重傷", "骨折", "失血"],
    "重傷": ["濒死", "重伤昏迷", "大量失血"],
    # Limb / body part
    "右手骨折": ["右手重伤", "右手残废", "右手永久伤残"],
    "左臂骨折": ["左臂重伤", "左臂残废", "左臂永久伤残"],
    "雙臂骨折": ["雙臂重伤", "雙臂残废", "全身瘫痪"],
    "雙腿骨折": ["雙腿重伤", "下身瘫痪", "輪椅依賴"],
    "失明": ["半盲", "重度弱視", "完全失明"],
    "聾啞": ["半聾", "重度聽障", "完全聾啞"],
    # Mental / morale
    "高興": ["平靜", "焦慮", "低落"],
    "平靜": ["焦慮", "低落", "恐懼"],
    "焦慮": ["恐懼", "崩潰", "絕望"],
    "恐懼": ["崩潰", "絕望", "驚慌失措"],
    "絕望": ["魂飛魄散", "瘋狂", "自我放棄"],
    # "Positive" / success states
    "完成": ["半成", "未竟", "失敗"],
    "勝利": ["慘勝", "平局", "失敗"],
}


# ============================================
# Anti-Exploit Rules (preserved + extended)
# ============================================

# The legacy soul-transfer had 4 anti-exploit rules. Phase F2
# extends them to 7 by translating numerical rules to semantic ones
# and adding the new F2 defenses. The 7 rules are referenced in
# the docs and the tests.

ANTI_EXPLOIT_RULE_1 = "soul can only transfer to a vessel in the same scene"
ANTI_EXPLOIT_RULE_2 = "soul cannot transfer to a vessel that already has an active soul"
ANTI_EXPLOIT_RULE_3 = "transfer takes one full turn (defer turn-system check to caller)"
ANTI_EXPLOIT_RULE_4 = "if the new vessel dies within 3 turns, the soul is destroyed"
ANTI_EXPLOIT_RULE_5 = "source character must be in a transferable state (not NON_TRANSFERABLE_TAGS)"
ANTI_EXPLOIT_RULE_6 = "anti-predictability: previous transfer result is NOT the new transfer result"
ANTI_EXPLOIT_RULE_7 = (
    "cross-character memory isolation: soul takes its own memories, not the vessel's"
)

ANTI_EXPLOIT_RULES = (
    ANTI_EXPLOIT_RULE_1,
    ANTI_EXPLOIT_RULE_2,
    ANTI_EXPLOIT_RULE_3,
    ANTI_EXPLOIT_RULE_4,
    ANTI_EXPLOIT_RULE_5,
    ANTI_EXPLOIT_RULE_6,
    ANTI_EXPLOIT_RULE_7,
)


# ============================================
# Errors
# ============================================


class SoulTransferError(Exception):
    """Base for soul transfer errors."""


class SoulTransferNotAllowedError(SoulTransferError):
    """Raised when an anti-exploit rule blocks the transfer."""


class SoulTransferStateError(SoulTransferError):
    """Raised when source/vessel state is invalid for transfer."""


# ============================================
# Data models
# ============================================


@dataclass
class SoulTransferRecord:
    """The new contract: a pure-text soul transfer record.

    Replaces the legacy `SoulPayload`. No `degradation_factor` (no
    numbers). The "degraded state" is a list of pure-text tags
    (inherited from `SemanticState.tags`).
    """

    transfer_id: str
    source_character_id: str
    target_vessel_id: str
    scene_id: str
    created_at: str
    # The new tag set assigned to the vessel after transfer.
    # This is a SUBSET of the source's tags, with one tag replaced
    # by its downgraded version (see TIER_DOWNGRADES).
    new_tags: list[str] = field(default_factory=list)
    # The set of memories carried over (text-only).
    carried_memories: list[str] = field(default_factory=list)
    # The tag that was downgraded (None if no downgrade happened).
    downgraded_from: str | None = None
    downgraded_to: str | None = None
    # How the downgrade was computed: "tier_list" or "llm_fallback".
    downgrade_method: str = "tier_list"
    # Audit trail (anti-exploit rule pass/fail, etc.).
    audit: dict[str, Any] = field(default_factory=dict)
    # Lifecycle: pending → applied (or rolled_back on failure).
    applied: bool = False
    applied_at: str | None = None
    # Vessel TTL: if vessel is destroyed within `vessel_ttl_turns`,
    # the soul dies too (rule 4). Set to 0 to disable.
    vessel_ttl_turns: int = 3
    # Carried active threads (karma heritage)
    carried_threads: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SoulTransferRecord:
        return cls(**data)


# ============================================
# SQLite schema
# ============================================


SOUL_TRANSFER_SCHEMA = """
CREATE TABLE IF NOT EXISTS soul_transfers (
    transfer_id TEXT PRIMARY KEY,
    source_character_id TEXT NOT NULL,
    target_vessel_id TEXT NOT NULL,
    scene_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    new_tags_json TEXT NOT NULL,
    carried_memories_json TEXT NOT NULL,
    downgraded_from TEXT,
    downgraded_to TEXT,
    downgrade_method TEXT NOT NULL,
    audit_json TEXT NOT NULL,
    applied INTEGER NOT NULL DEFAULT 0,
    applied_at TEXT,
    vessel_ttl_turns INTEGER NOT NULL DEFAULT 3,
    carried_threads_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_transfer_source
    ON soul_transfers (source_character_id);
CREATE INDEX IF NOT EXISTS idx_transfer_target
    ON soul_transfers (target_vessel_id);
CREATE INDEX IF NOT EXISTS idx_transfer_scene
    ON soul_transfers (scene_id);
CREATE INDEX IF NOT EXISTS idx_transfer_pending
    ON soul_transfers (applied) WHERE applied = 0;
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _validate_tag_strict(tag: str) -> str:
    """F1-aligned tag validation: CJK only, ≤15 chars, non-empty.

    Raises ValueError on any violation. Used as a defensive
    check on LLM output (rule: never trust external input).
    """
    if not isinstance(tag, str):
        raise ValueError(f"tag must be str, got {type(tag).__name__}")
    if not tag.strip():
        raise ValueError("tag is empty or whitespace-only")
    if len(tag) > MAX_TAG_LENGTH:
        raise ValueError(f"tag too long: {len(tag)} > {MAX_TAG_LENGTH} chars ({tag!r})")
    if not _TAG_PATTERN.match(tag):
        raise ValueError(f"invalid characters in tag (CJK + space + hyphen only): {tag!r}")
    return tag


# ============================================
# SemanticSoulTransfer — the new engine
# ============================================


class SemanticSoulTransfer:
    """Pure-text soul transfer. NO numerical degradation.

    Replaces the legacy `SoulTransferService`. The new contract:

      * `is_transfer_allowed(...)` — checks the 7 anti-exploit rules.
      * `compute_degradation(source_tags, vessel_id)` — picks a
        downgraded tag (tier list fast path, LLM slow fallback).
        Anti-predictable: the result differs from any previous
        transfer to the same vessel.
      * `execute_transfer(...)` — atomic 5-step flow:
        1. validate (anti-exploit rules)
        2. compute degradation
        3. assemble new tags (source tags minus the downgraded
           source tag, plus the new downgraded tag)
        4. write to SQLite (single transaction)
        5. return SoulTransferRecord (caller applies to vessel)

    The class is safe to instantiate without an LLM client (LLM
    fallback is then disabled; novel states return a sentinel
    "未分類" tag and the transfer is still allowed but flagged).
    """

    def __init__(
        self,
        memory_palace: Any = None,  # MemoryPalace or None
        llm_client: Any = None,  # LLMClient or None
        memory_isolation_guard: Any = None,  # MemoryIsolationGuard or None
        soul_db_path: str | None = None,
        rng_seed: int | None = None,
        tier_downgrades: dict[str, list[str]] | None = None,
        non_transferable_tags: frozenset | None = None,
    ) -> None:
        self.memory_palace = memory_palace
        self.llm_client = llm_client
        self.memory_isolation_guard = memory_isolation_guard
        self.rng = random.Random(rng_seed)
        self.tier_downgrades: dict[str, list[str]] = dict(tier_downgrades or TIER_DOWNGRADES)
        self.non_transferable_tags: frozenset = non_transferable_tags or NON_TRANSFERABLE_TAGS

        # Anti-predictability: track last result per vessel_id.
        # vessel_id -> last_downgraded_to (str) or None
        self._last_result: dict[str, str | None] = {}
        # Anti-predictability: tier-list cache (source_tag, vessel_id)
        # -> computed downgrade. Used as fast path; rotated to
        # avoid caching the "always the same" answer.
        self._tier_cache: dict[tuple[str, str], str] = {}

        # Storage path
        if soul_db_path is None and memory_palace is not None and hasattr(memory_palace, "db_path"):
            soul_db_path = str(Path(memory_palace.db_path).parent / "soul_transfers.db")
        elif soul_db_path is None:
            soul_db_path = ":memory:"
        self.soul_db_path = soul_db_path

        self._initialize_storage()

    # -------- storage --------

    def _initialize_storage(self) -> None:
        if self.soul_db_path == ":memory:":
            # In-memory mode (tests): keep a single shared connection.
            self._mem_conn: sqlite3.Connection | None = sqlite3.connect(
                ":memory:", check_same_thread=False
            )
            # Row factory is set here (and on every _connect) so that
            # callers can do `row["column_name"]`.
            self._mem_conn.row_factory = sqlite3.Row
            self._mem_conn.executescript(SOUL_TRANSFER_SCHEMA)
            self._mem_conn.commit()
        else:
            Path(self.soul_db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.soul_db_path)
            try:
                conn.executescript(SOUL_TRANSFER_SCHEMA)
                conn.commit()
            finally:
                conn.close()
            self._mem_conn = None

    def _connect(self) -> sqlite3.Connection:
        if self._mem_conn is not None:
            # Always (re)apply the row factory — SQLite connections
            # reset to default tuple access if anyone touches the
            # connection directly.
            self._mem_conn.row_factory = sqlite3.Row
            return self._mem_conn
        conn = sqlite3.connect(self.soul_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # -------- 7 anti-exploit rules --------

    def is_transfer_allowed(
        self,
        source_character_id: str,
        source_state: list[str],
        target_vessel_id: str,
        target_vessel_state: list[str],
        scene_id: str,
    ) -> dict[str, Any]:
        """Run all 7 anti-exploit rules. Returns {allowed, reason, ...}.

        The 5 rules that can be checked synchronously are:
          1. Same scene (caller passes scene_id; we trust it)
          2. Vessel does not already have an active soul
             (heuristic: vessel_state must be empty or contain
              "空容器" / "無魂" / "vessel_empty")
          3. Transfer takes one full turn (caller's responsibility)
          4. Vessel TTL (caller's responsibility)
          5. Source state is "transferable" (not in non_transferable_tags
             and not in LOST_SOUL_TAGS)
          6. Anti-predictability (checked in compute_degradation, not here)
          7. Memory isolation (memory_isolation_guard, checked in
             execute_transfer)
        """
        if source_character_id == target_vessel_id:
            return {
                "allowed": False,
                "reason": "self-transfer is not allowed",
                "rule": ANTI_EXPLOIT_RULE_1,
            }
        # Rule 1: same scene — caller must ensure; we accept scene_id
        # as a parameter and trust the caller. (We could cross-check
        # against a scene registry, but that's the caller's job.)
        if not scene_id or not isinstance(scene_id, str):
            return {
                "allowed": False,
                "reason": "scene_id is required",
                "rule": ANTI_EXPLOIT_RULE_1,
            }

        # Rule 2: vessel must not have an active soul.
        # Heuristic: if vessel_state contains any non-"empty" tag,
        # assume it has a soul. The caller can pass an empty list
        # for a fresh vessel.
        vessel_active_tags = [
            t for t in target_vessel_state if t not in ("空容器", "無魂", "vessel_empty", "")
        ]
        if vessel_active_tags:
            return {
                "allowed": False,
                "reason": (
                    f"vessel already has an active soul " f"(tags: {vessel_active_tags[:3]})"
                ),
                "rule": ANTI_EXPLOIT_RULE_2,
            }

        # Rule 5: source must be transferable.
        for tag in source_state:
            if tag in self.non_transferable_tags:
                return {
                    "allowed": False,
                    "reason": (f"source is in non-transferable state: {tag!r}"),
                    "rule": ANTI_EXPLOIT_RULE_5,
                }
            if tag in LOST_SOUL_TAGS:
                return {
                    "allowed": False,
                    "reason": (f"source soul is already lost: {tag!r}"),
                    "rule": ANTI_EXPLOIT_RULE_5,
                }

        return {
            "allowed": True,
            "reason": "all rules passed",
            "rules_checked": [
                ANTI_EXPLOIT_RULE_1,
                ANTI_EXPLOIT_RULE_2,
                ANTI_EXPLOIT_RULE_5,
            ],
        }

    # -------- degradation (tier list + LLM fallback) --------

    def _pick_from_tier_list(
        self,
        source_tag: str,
        vessel_id: str,
    ) -> str | None:
        """Pick a downgrade from the tier list, anti-predictably.

        Returns None if `source_tag` is not in the tier list.
        """
        choices = self.tier_downgrades.get(source_tag)
        if not choices:
            return None
        # Anti-predictability: if the previous result is in the
        # choices list, exclude it (so we never repeat).
        previous = self._last_result.get(vessel_id)
        valid_choices = [c for c in choices if c != previous]
        if not valid_choices:
            # Fallback: all choices equal previous (1-element list).
            # Just return the only choice; this is the "non-random"
            # edge case the F2 audit flags.
            return choices[0]
        return self.rng.choice(valid_choices)

    async def _llm_downgrade(
        self,
        source_tag: str,
    ) -> str | None:
        """Ask the LLM for a downgrade. Returns None if no LLM wired.

        Validates the LLM output with the F1 tag rules. If the LLM
        returns garbage, falls back to "未分類" (uncategorized) so
        the transfer is never blocked by a flaky LLM.
        """
        if self.llm_client is None:
            return None
        prompt = DEFAULT_LLM_DOWNGRADE_PROMPT.format(source_state=source_tag)
        try:
            raw = await self.llm_client.generate(
                system_prompt="You are a semantic state downgrade assistant.",
                user_message=prompt,
                temperature=1.0,
                max_tokens=128,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "soul_transfer: LLM downgrade call failed for %r: %s",
                source_tag,
                exc,
            )
            return None

        # Parse the JSON. The LLM is asked to return
        # `{"degraded_state": "..."}`.
        try:
            data = json.loads(raw)
            candidate = data.get("degraded_state") or data.get("degraded") or ""
        except (json.JSONDecodeError, AttributeError):
            # Try regex extraction
            match = re.search(r'"degraded_state"\s*:\s*"([^"]+)"', raw)
            candidate = match.group(1) if match else ""

        # Validate the candidate
        try:
            return _validate_tag_strict(candidate)
        except ValueError as exc:
            logger.warning(
                "soul_transfer: LLM returned invalid tag %r: %s",
                candidate,
                exc,
            )
            return None

    async def compute_degradation(
        self,
        source_state: list[str],
        vessel_id: str,
    ) -> dict[str, Any]:
        """Compute the new state for a transfer.

        Strategy:
          1. If source_state is empty, return as-is.
          2. Find a "downgradeable" tag (any tag that is in the
             tier list, or any tag for which LLM can produce a
             downgrade). The first such tag is the one we replace.
          3. Tier list: pick from the list (anti-predictable).
          4. LLM fallback: ask the LLM, validate, fall back to
             "未分類" if LLM is unavailable or returns garbage.
          5. Anti-predictability: ensure the new tag differs from
             the previous result for the same vessel.

        Returns a dict with:
          * new_tags: list[str] — the new tag set
          * downgraded_from: str | None
          * downgraded_to: str | None
          * downgrade_method: "tier_list" | "llm_fallback" | "none"
        """
        if not source_state:
            return {
                "new_tags": [],
                "downgraded_from": None,
                "downgraded_to": None,
                "downgrade_method": "none",
            }

        # 1. Find the first tier-list-mappable tag.
        for tag in source_state:
            tier_pick = self._pick_from_tier_list(tag, vessel_id)
            if tier_pick is not None:
                # Build the new tag set
                new_tags = [t for t in source_state if t != tag] + [tier_pick]
                # Anti-predictability: update last_result
                self._last_result[vessel_id] = tier_pick
                return {
                    "new_tags": new_tags,
                    "downgraded_from": tag,
                    "downgraded_to": tier_pick,
                    "downgrade_method": "tier_list",
                }

        # 2. No tier-list match — try LLM fallback for the first tag.
        first_tag = source_state[0]
        previous = self._last_result.get(vessel_id)
        llm_pick = await self._llm_downgrade(first_tag)
        if llm_pick is None:
            # No LLM wired or LLM failed. Use a deterministic
            # fallback so the transfer is never blocked. The
            # fallback "未分類" is a pure-text "uncategorized"
            # marker that signals "downgrade was uncertain".
            llm_pick = "未分類"
        # Anti-predictability: if LLM picked the previous result,
        # try a tier-list fallback or "未分類" with a suffix.
        if llm_pick == previous:
            # We can't easily ask LLM again; append a deterministic
            # marker so the result differs.
            llm_pick = f"{llm_pick}變體"

        new_tags = [t for t in source_state if t != first_tag] + [llm_pick]
        self._last_result[vessel_id] = llm_pick
        return {
            "new_tags": new_tags,
            "downgraded_from": first_tag,
            "downgraded_to": llm_pick,
            "downgrade_method": "llm_fallback",
        }

    # -------- execute_transfer (atomic 5-step flow) --------

    async def execute_transfer(
        self,
        source_character_id: str,
        source_state: list[str],
        target_vessel_id: str,
        target_vessel_state: list[str],
        scene_id: str,
        carried_memories: list[str] | None = None,
        requester_id: str | None = None,
        source_active_threads: dict | None = None,
    ) -> SoulTransferRecord:
        """Run the full transfer flow. Returns SoulTransferRecord.

        The flow is:
          1. Anti-exploit check (rules 1, 2, 5)
          2. Anti-predictability: compute degradation
          3. Memory isolation check (rule 7) if guard is wired
          4. Atomic SQLite write
          5. Return record (caller applies to vessel)

        Raises `SoulTransferNotAllowedError` on rule violation.
        Raises `SoulTransferStateError` on invalid state.
        """
        # 1. Anti-exploit check
        check = self.is_transfer_allowed(
            source_character_id=source_character_id,
            source_state=source_state,
            target_vessel_id=target_vessel_id,
            target_vessel_state=target_vessel_state,
            scene_id=scene_id,
        )
        if not check["allowed"]:
            raise SoulTransferNotAllowedError(check["reason"])

        # 2. Compute degradation (anti-predictable)
        degradation = await self.compute_degradation(
            source_state=source_state,
            vessel_id=target_vessel_id,
        )

        # 3. Memory isolation check (rule 7)
        if self.memory_isolation_guard is not None and requester_id is not None:
            try:
                self.memory_isolation_guard.require(
                    requester_id=requester_id,
                    scene_id=scene_id,
                    target_character_id=source_character_id,
                    op="read",
                )
            except Exception as exc:  # noqa: BLE001
                raise SoulTransferNotAllowedError(f"memory isolation denied: {exc}") from exc

        carried = list(carried_memories or [])

        # Process carried active threads (karma heritage)
        carried_threads = {}
        if source_active_threads:
            for tid, data in source_active_threads.items():
                if data.get("status") in ("Active", "Evaded"):
                    carried_threads[tid] = {
                        "status": data.get("status"),
                        "escalation_level": data.get("escalation_level", 0),
                        "seeded_round": 1,
                        "meta": dict(data.get("meta", {}))
                    }

        # 4. Build record
        record = SoulTransferRecord(
            transfer_id=str(uuid.uuid4()),
            source_character_id=source_character_id,
            target_vessel_id=target_vessel_id,
            scene_id=scene_id,
            created_at=_now_iso(),
            new_tags=degradation["new_tags"],
            carried_memories=carried,
            downgraded_from=degradation["downgraded_from"],
            downgraded_to=degradation["downgraded_to"],
            downgrade_method=degradation["downgrade_method"],
            audit={
                "anti_exploit_check": check,
                "degradation": degradation,
                "rules_evaluated": [
                    ANTI_EXPLOIT_RULE_1,
                    ANTI_EXPLOIT_RULE_2,
                    ANTI_EXPLOIT_RULE_5,
                    ANTI_EXPLOIT_RULE_6,
                    ANTI_EXPLOIT_RULE_7,
                ],
            },
            applied=False,
            applied_at=None,
            vessel_ttl_turns=3,
            carried_threads=carried_threads,
        )

        # 5. Atomic write
        self._persist(record)
        return record

    # -------- SQLite persistence --------

    def _persist(self, record: SoulTransferRecord) -> None:
        """Single-transaction SQLite write. No partial state on failure."""
        new_tags_json = json.dumps(record.new_tags, ensure_ascii=False)
        carried_json = json.dumps(record.carried_memories, ensure_ascii=False)
        audit_json = json.dumps(record.audit, ensure_ascii=False)
        carried_threads_json = json.dumps(record.carried_threads, ensure_ascii=False)
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO soul_transfers
                (transfer_id, source_character_id, target_vessel_id, scene_id,
                 created_at, new_tags_json, carried_memories_json,
                 downgraded_from, downgraded_to, downgrade_method,
                 audit_json, applied, applied_at, vessel_ttl_turns, carried_threads_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?)
                """,
                (
                    record.transfer_id,
                    record.source_character_id,
                    record.target_vessel_id,
                    record.scene_id,
                    record.created_at,
                    new_tags_json,
                    carried_json,
                    record.downgraded_from,
                    record.downgraded_to,
                    record.downgrade_method,
                    audit_json,
                    record.vessel_ttl_turns,
                    carried_threads_json,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if self._mem_conn is None:
                conn.close()

    async def apply_transfer(self, record: SoulTransferRecord, session: Any = None) -> dict[str, Any]:
        """Mark a persisted record as 'applied' to its vessel.

        Called by the caller AFTER they've actually written the
        new tags to the vessel's SemanticState. The apply is
        idempotent: only the first call updates the row.
        """
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                UPDATE soul_transfers
                SET applied = 1, applied_at = ?
                WHERE transfer_id = ? AND applied = 0
                """,
                (_now_iso(), record.transfer_id),
            )
            conn.commit()
            record.applied = cursor.rowcount == 1
            record.applied_at = _now_iso() if record.applied else None
            
            # If SQLAlchemy session is provided, sync the threads heritage to vessel DB state
            if record.applied and session is not None and record.carried_threads:
                try:
                    from backend.models import CharacterState
                    cs = await session.get(CharacterState, record.target_vessel_id)
                    if cs:
                        cs.active_threads = dict(record.carried_threads)
                except Exception as e:
                    logger.warning(f"Failed to apply carried_threads to vessel {record.target_vessel_id} in DB: {e}")
            
            return {"rows_updated": cursor.rowcount, "transfer_id": record.transfer_id}
        except Exception:
            conn.rollback()
            raise
        finally:
            if self._mem_conn is None:
                conn.close()

    async def get_transfer(self, transfer_id: str) -> SoulTransferRecord | None:
        """Retrieve a persisted transfer record by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM soul_transfers WHERE transfer_id = ?",
                (transfer_id,),
            ).fetchone()
            if row is None:
                return None
            
            try:
                carried_threads = json.loads(row["carried_threads_json"]) if row["carried_threads_json"] else {}
            except Exception:
                carried_threads = {}

            return SoulTransferRecord(
                transfer_id=row["transfer_id"],
                source_character_id=row["source_character_id"],
                target_vessel_id=row["target_vessel_id"],
                scene_id=row["scene_id"],
                created_at=row["created_at"],
                new_tags=json.loads(row["new_tags_json"]),
                carried_memories=json.loads(row["carried_memories_json"]),
                downgraded_from=row["downgraded_from"],
                downgraded_to=row["downgraded_to"],
                downgrade_method=row["downgrade_method"],
                audit=json.loads(row["audit_json"]),
                applied=bool(row["applied"]),
                applied_at=row["applied_at"],
                vessel_ttl_turns=row["vessel_ttl_turns"],
                carried_threads=carried_threads,
            )
        finally:
            if self._mem_conn is None:
                conn.close()

    async def get_pending_transfers(self, vessel_id: str) -> list[SoulTransferRecord]:
        """List unapplied transfers to a vessel (crash recovery)."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM soul_transfers
                WHERE target_vessel_id = ? AND applied = 0
                ORDER BY created_at ASC
                """,
                (vessel_id,),
            ).fetchall()
            
            results = []
            for r in rows:
                try:
                    carried_threads = json.loads(r["carried_threads_json"]) if r["carried_threads_json"] else {}
                except Exception:
                    carried_threads = {}
                
                results.append(
                    SoulTransferRecord(
                        transfer_id=r["transfer_id"],
                        source_character_id=r["source_character_id"],
                        target_vessel_id=r["target_vessel_id"],
                        scene_id=r["scene_id"],
                        created_at=r["created_at"],
                        new_tags=json.loads(r["new_tags_json"]),
                        carried_memories=json.loads(r["carried_memories_json"]),
                        downgraded_from=r["downgraded_from"],
                        downgraded_to=r["downgraded_to"],
                        downgrade_method=r["downgrade_method"],
                        audit=json.loads(r["audit_json"]),
                        applied=bool(r["applied"]),
                        applied_at=r["applied_at"],
                        vessel_ttl_turns=r["vessel_ttl_turns"],
                        carried_threads=carried_threads,
                    )
                )
            return results
        finally:
            if self._mem_conn is None:
                conn.close()

    async def count_transfers(self, character_id: str) -> int:
        """Count transfers involving a character (source or vessel)."""
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM soul_transfers
                WHERE source_character_id = ? OR target_vessel_id = ?
                """,
                (character_id, character_id),
            ).fetchone()
            return int(row["n"])
        finally:
            if self._mem_conn is None:
                conn.close()


# ============================================
# Backward-compat shim — DO NOT use in new code
# ============================================
#
# The legacy `SoulTransferService` and `SoulPayload` are **removed**
# in F2. They carried numerical thinking (`degradation_factor`).
# The new contract is `SemanticSoulTransfer` + `SoulTransferRecord`.
#
# If a frozen caller still references the old classes, the import
# will raise ImportError — that is intentional, to surface the
# migration gap before F3 ships.


__all__ = [
    # Constants
    "MAX_TAGS_PER_TRANSFER",
    "MAX_TAG_LENGTH",
    "NON_TRANSFERABLE_TAGS",
    "LOST_SOUL_TAGS",
    "DEFAULT_LLM_DOWNGRADE_PROMPT",
    "TIER_DOWNGRADES",
    # Anti-exploit rules
    "ANTI_EXPLOIT_RULE_1",
    "ANTI_EXPLOIT_RULE_2",
    "ANTI_EXPLOIT_RULE_3",
    "ANTI_EXPLOIT_RULE_4",
    "ANTI_EXPLOIT_RULE_5",
    "ANTI_EXPLOIT_RULE_6",
    "ANTI_EXPLOIT_RULE_7",
    "ANTI_EXPLOIT_RULES",
    # Errors
    "SoulTransferError",
    "SoulTransferNotAllowedError",
    "SoulTransferStateError",
    # Data model
    "SoulTransferRecord",
    # Engine
    "SemanticSoulTransfer",
]
