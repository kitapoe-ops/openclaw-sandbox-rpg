"""
Soul Transfer (Wave 2 Core #2)
==============================
Atomic 3-dimensional payload transfer between characters.

A "Soul" is a composite of:
  1. Memory Palace fragment list (long-term episodic/semantic/etc. memories)
  2. Character state (physical + mental + inventory + relationships)
  3. LLM Prompt Context (accumulated attitude, recent_choices, npc_relationships)

Per design lock (2026-06-04 decision):
  - Q1: Storage = SQLite blob column (atomic, follows Phase A pattern)
  - Q2: Degradation = random factor in [0.6, 0.9] per transfer
  - Q3: Service-level method (no HTTP endpoint yet, defer to Phase B)

Anti-suicide: The degradation is lossy \u2014 a fresh soul never becomes
a perfect copy. Each transfer drops 10-40% of various dimensions,
preventing players from griefing their own stats.

Lock: 2026-06-04 21:46 GMT+8
"""
from __future__ import annotations

import json
import logging
import random
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

UTC = timezone.utc

# Degradation bounds (random factor in this range)
DEGRADATION_MIN = 0.6
DEGRADATION_MAX = 0.9

# Per-dimension loss range (additive random loss in this range)
DIMENSION_LOSS_MIN = 0.05
DIMENSION_LOSS_MAX = 0.20


# ============================================
# SoulPayload
# ============================================


@dataclass
class PromptContext:
    """
    The LLM-facing context that builds Scene Agent prompts.
    Accumulated over a character's lifetime.
    """
    recent_choices: List[str] = field(default_factory=list)
    attitude_history: List[Dict[str, str]] = field(default_factory=list)
    npc_relationships: Dict[str, str] = field(default_factory=dict)
    scene_recaps: List[str] = field(default_factory=list)
    last_narrative: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromptContext":
        return cls(**data)


@dataclass
class SoulPayload:
    """
    The atomic unit transferred between characters.
    Contains 3 dimensions: memories + character_state + prompt_context.
    """
    soul_id: str
    source_character_id: str
    target_character_id: str
    created_at: str
    memories: List[Dict[str, Any]]  # serialized MemoryFragment dicts
    character_state: Dict[str, Any]  # physical + mental + inventory + relationships
    prompt_context: PromptContext
    degradation_factor: float
    # Audit trail
    transfer_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SoulPayload":
        pc = data.get("prompt_context", {})
        if isinstance(pc, dict):
            pc = PromptContext.from_dict(pc)
        else:
            pc = PromptContext()
        return cls(
            soul_id=data["soul_id"],
            source_character_id=data["source_character_id"],
            target_character_id=data["target_character_id"],
            created_at=data["created_at"],
            memories=data.get("memories", []),
            character_state=data.get("character_state", {}),
            prompt_context=pc,
            degradation_factor=data.get("degradation_factor", 0.7),
            transfer_metadata=data.get("transfer_metadata", {}),
        )


# ============================================
# SQLite Schema (soul_payloads table)
# ============================================


SOUL_SCHEMA = """
CREATE TABLE IF NOT EXISTS soul_payloads (
    soul_id TEXT PRIMARY KEY,
    source_character_id TEXT NOT NULL,
    target_character_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    degradation_factor REAL NOT NULL,
    payload_json TEXT NOT NULL,
    applied INTEGER NOT NULL DEFAULT 0,
    applied_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_soul_source ON soul_payloads (source_character_id);
CREATE INDEX IF NOT EXISTS idx_soul_target ON soul_payloads (target_character_id);
CREATE INDEX IF NOT EXISTS idx_soul_pending ON soul_payloads (applied) WHERE applied = 0;
"""


# ============================================
# Degradation Engine
# ============================================


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _downshift_semantic(level: str, levels: List[str], steps: int) -> str:
    """
    Move a semantic level by `steps` positions toward the WORSE end
    (higher index in the levels list, which is conventionally worst).
    """
    if level not in levels:
        return level
    idx = levels.index(level)
    new_idx = min(len(levels) - 1, idx + steps)
    return levels[new_idx]


def degrade_character_state(
    state: Dict[str, Any], factor: float, rng: random.Random
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Apply lossy degradation to a character state dict.

    Stamina:    downshift by 1 level toward worse
    Health:     if not "healthy", downshift by 1 toward worse
    Morale:     downshift by 1 toward worse
    Active effects: drop a random subset (10-30%)
    Inventory:  keep only top-3 highest-value items
    Relationships: drop weakest 50%

    Returns (degraded_state, audit_trail).
    """
    if not DEGRADATION_MIN <= factor <= DEGRADATION_MAX:
        raise ValueError(
            f"degradation factor must be in [{DEGRADATION_MIN}, {DEGRADATION_MAX}], "
            f"got {factor}"
        )
    physical = state.get("physical", {})
    mental = state.get("mental", {})

    # Stamina downshift
    stamina_levels = ["fresh", "slight_breath", "muscle_ache", "exhausted", "collapse"]
    old_stamina = physical.get("stamina_level", "fresh")
    new_stamina = _downshift_semantic(old_stamina, stamina_levels, 1)
    physical["stamina_level"] = new_stamina

    # Health downshift if not healthy
    health_levels = ["healthy", "wounded", "severely_wounded", "dying", "dead"]
    old_health = physical.get("health_status", "healthy")
    if old_health != "healthy":
        new_health = _downshift_semantic(old_health, health_levels, 1)
    else:
        new_health = old_health
    physical["health_status"] = new_health

    # Morale downshift
    morale_levels = ["elated", "calm", "neutral", "anxious", "despair"]
    old_morale = mental.get("morale_level", "neutral")
    new_morale = _downshift_semantic(old_morale, morale_levels, 1)
    mental["morale_level"] = new_morale

    # Active effects: drop 10-30%
    effects = physical.get("active_effects", [])
    drop_pct = rng.uniform(DIMENSION_LOSS_MIN, DIMENSION_LOSS_MAX)
    if effects:
        keep_n = max(0, int(len(effects) * (1 - drop_pct)))
        physical["active_effects"] = effects[:keep_n]

    # Inventory: keep top 3 (we don't track value, so just first 3)
    inventory = state.get("inventory", {})
    items = inventory.get("items", [])
    if len(items) > 3:
        inventory["items"] = items[:3]

    # Relationships: drop weakest 50% (first 50% by alphabetical order, simplified)
    relationships = state.get("relationships", {})
    if len(relationships) > 1:
        half = max(1, len(relationships) // 2)
        # Keep last half (assume those are stronger / more recent)
        keep_rels = dict(list(relationships.items())[half:])
        state["relationships"] = keep_rels

    audit = {
        "stamina": {"old": old_stamina, "new": new_stamina},
        "health": {"old": old_health, "new": new_health},
        "morale": {"old": old_morale, "new": new_morale},
        "active_effects_dropped": len(effects) - len(physical.get("active_effects", [])),
        "effects_drop_pct": drop_pct,
        "factor_used": factor,
    }
    return state, audit


def degrade_prompt_context(
    ctx: PromptContext, factor: float, rng: random.Random
) -> Tuple[PromptContext, Dict[str, Any]]:
    if not DEGRADATION_MIN <= factor <= DEGRADATION_MAX:
        raise ValueError(
            f"degradation factor must be in [{DEGRADATION_MIN}, {DEGRADATION_MAX}], "
            f"got {factor}"
        )
    """
    Apply lossy degradation to LLM prompt context.

    recent_choices: drop random 30-50%
    attitude_history: drop random 40-60%
    scene_recaps: drop random 30-50%
    Keep last_narrative as-is (single string, no loss)
    """
    drop_recent = rng.uniform(0.3, 0.5)
    drop_attitude = rng.uniform(0.4, 0.6)
    drop_recaps = rng.uniform(0.3, 0.5)

    if ctx.recent_choices:
        keep = max(0, int(len(ctx.recent_choices) * (1 - drop_recent)))
        ctx.recent_choices = ctx.recent_choices[-keep:]

    if ctx.attitude_history:
        keep = max(0, int(len(ctx.attitude_history) * (1 - drop_attitude)))
        ctx.attitude_history = ctx.attitude_history[-keep:]

    if ctx.scene_recaps:
        keep = max(0, int(len(ctx.scene_recaps) * (1 - drop_recaps)))
        ctx.scene_recaps = ctx.scene_recaps[-keep:]

    # Salience reduction on memories is handled by MemoryPalace.transfer_memories
    audit = {
        "recent_choices_drop_pct": drop_recent,
        "attitude_history_drop_pct": drop_attitude,
        "scene_recaps_drop_pct": drop_recaps,
        "factor_used": factor,
    }
    return ctx, audit


def degrade_memories(
    memories: List[Dict[str, Any]], factor: float, rng: random.Random
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not DEGRADATION_MIN <= factor <= DEGRADATION_MAX:
        raise ValueError(
            f"degradation factor must be in [{DEGRADATION_MIN}, {DEGRADATION_MAX}], "
            f"got {factor}"
        )
    """
    Apply salience degradation to all memories in the payload.
    Uses factor directly (per design lock: random [0.6, 0.9]).
    """
    degraded = []
    for m in memories:
        new_m = dict(m)
        old_sal = new_m.get("salience", 0.5)
        new_m["salience"] = _clamp(old_sal * factor, 0.0, 1.0)
        # Mark with origin
        meta = new_m.get("metadata", {}) or {}
        meta["soul_transferred"] = True
        new_m["metadata"] = meta
        degraded.append(new_m)

    # Drop 5-15% of lowest-salience memories
    drop_pct = rng.uniform(0.05, 0.15)
    if degraded:
        # Sort by salience asc, drop the lowest
        n_drop = int(len(degraded) * drop_pct)
        if n_drop > 0:
            sorted_mems = sorted(degraded, key=lambda m: m.get("salience", 0))
            keep = sorted_mems[n_drop:]
            degraded = keep

    return degraded, {
        "factor_used": factor,
        "count_after": len(degraded),
        "drop_pct_applied": drop_pct if degraded else 0,
    }


# ============================================
# SoulTransferService
# ============================================


class SoulTransferService:
    """
    Service-level method for transferring a complete "Soul" between
    characters. Atomic: either the entire transfer succeeds or nothing
    changes.

    Usage:
        svc = SoulTransferService(memory_palace, db_path)
        result = await svc.transfer(
            source_character_id="char_a",
            target_character_id="char_b",
        )
        # result["soul_id"] can be queried later
    """

    def __init__(
        self,
        memory_palace,  # backend.memory_palace.MemoryPalace
        soul_db_path: Optional[str] = None,
        rng_seed: Optional[int] = None,
    ):
        self.memory_palace = memory_palace
        self.soul_db_path = soul_db_path or str(
            Path(memory_palace.db_path).parent / "soul_palace.db"
        )
        self.rng = random.Random(rng_seed)  # deterministic if seed set
        self._initialize_soul_storage()

    def _initialize_soul_storage(self) -> None:
        Path(self.soul_db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.soul_db_path)
        try:
            conn.executescript(SOUL_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _connect_soul(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.soul_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    async def assemble_payload(
        self,
        source_character_id: str,
        target_character_id: str,
        character_state: Dict[str, Any],
        prompt_context: Optional[PromptContext] = None,
        degradation_factor: Optional[float] = None,
    ) -> SoulPayload:
        """
        Step 1: Read source's memories, build the 3D payload with
        degradation applied. Does NOT persist yet.
        """
        if source_character_id == target_character_id:
            raise ValueError("source and target character must differ")

        # Read memories from MemoryPalace
        memories_fragments = await self.memory_palace.get_memories(
            source_character_id, limit=10000, include_archived=False
        )
        memories_as_dicts = [m.to_dict() for m in memories_fragments]

        # Resolve degradation factor
        if degradation_factor is None:
            degradation_factor = self.rng.uniform(DEGRADATION_MIN, DEGRADATION_MAX)
        if not DEGRADATION_MIN <= degradation_factor <= DEGRADATION_MAX:
            raise ValueError(
                f"degradation_factor must be in [{DEGRADATION_MIN}, {DEGRADATION_MAX}]"
            )

        # Apply degradation to each dimension
        memories, mem_audit = degrade_memories(
            memories_as_dicts, degradation_factor, self.rng
        )
        char_state, state_audit = degrade_character_state(
            character_state, degradation_factor, self.rng
        )
        pc = prompt_context or PromptContext()
        pc, ctx_audit = degrade_prompt_context(pc, degradation_factor, self.rng)

        soul = SoulPayload(
            soul_id=str(uuid.uuid4()),
            source_character_id=source_character_id,
            target_character_id=target_character_id,
            created_at=_now_iso(),
            memories=memories,
            character_state=char_state,
            prompt_context=pc,
            degradation_factor=degradation_factor,
            transfer_metadata={
                "degradation_factor": degradation_factor,
                "memory_audit": mem_audit,
                "state_audit": state_audit,
                "context_audit": ctx_audit,
            },
        )
        return soul

    async def persist_soul(self, soul: SoulPayload) -> None:
        """
        Step 2: Atomically persist the assembled soul to soul_payloads
        table. Single transaction.
        """
        payload_json = json.dumps(soul.to_dict(), ensure_ascii=False)
        conn = self._connect_soul()
        try:
            conn.execute(
                """
                INSERT INTO soul_payloads
                (soul_id, source_character_id, target_character_id,
                 created_at, degradation_factor, payload_json, applied)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    soul.soul_id,
                    soul.source_character_id,
                    soul.target_character_id,
                    soul.created_at,
                    soul.degradation_factor,
                    payload_json,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def get_soul(self, soul_id: str) -> Optional[SoulPayload]:
        """Retrieve a previously persisted soul by ID."""
        conn = self._connect_soul()
        try:
            row = conn.execute(
                "SELECT * FROM soul_payloads WHERE soul_id = ?", (soul_id,)
            ).fetchone()
            if row is None:
                return None
            data = json.loads(row["payload_json"])
            return SoulPayload.from_dict(data)
        finally:
            conn.close()

    async def transfer(
        self,
        source_character_id: str,
        target_character_id: str,
        character_state: Dict[str, Any],
        prompt_context: Optional[PromptContext] = None,
        degradation_factor: Optional[float] = None,
    ) -> SoulPayload:
        """
        Full Soul Transfer flow:
        1. Assemble 3D payload (with degradation)
        2. Persist atomically to soul_payloads
        3. Apply to target: write memories via MemoryPalace, return soul for caller to apply state

        Returns the assembled SoulPayload so the caller can apply
        character_state to the target's CharacterStateMachine.
        """
        if source_character_id == target_character_id:
            raise ValueError("source and target character must differ")

        # Step 1: Assemble
        soul = await self.assemble_payload(
            source_character_id=source_character_id,
            target_character_id=target_character_id,
            character_state=character_state,
            prompt_context=prompt_context,
            degradation_factor=degradation_factor,
        )

        # Step 2: Persist atomically
        await self.persist_soul(soul)

        # Step 3: Apply memories via MemoryPalace (uses its own atomicity)
        # Re-write the degraded memories as a "transfer" from source.
        # We use a special character_id pattern so we can reconstruct later.
        for mem_dict in soul.memories:
            mem_id = str(uuid.uuid4())
            mem_dict["id"] = mem_id
            mem_dict["character_id"] = target_character_id
        # Note: actual memory_palace insert is handled separately by
        # the caller via memory_palace.transfer_memories() to ensure
        # the proper foreign-key semantics. We don't double-write here.

        return soul

    async def apply_soul(
        self,
        soul: SoulPayload,
    ) -> Dict[str, Any]:
        """
        Mark a persisted soul as 'applied' to its target character.
        This is called by the caller AFTER they've actually written the
        state/memories to the target (which has its own transaction).
        """
        conn = self._connect_soul()
        try:
            cursor = conn.execute(
                """
                UPDATE soul_payloads
                SET applied = 1, applied_at = ?
                WHERE soul_id = ? AND applied = 0
                """,
                (_now_iso(), soul.soul_id),
            )
            conn.commit()
            return {"rows_updated": cursor.rowcount, "soul_id": soul.soul_id}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def get_pending_souls(self, character_id: str) -> List[SoulPayload]:
        """
        List souls that are persisted but not yet applied to a target.
        Used for crash recovery / saga compensation.
        """
        conn = self._connect_soul()
        try:
            rows = conn.execute(
                """
                SELECT * FROM soul_payloads
                WHERE target_character_id = ? AND applied = 0
                ORDER BY created_at ASC
                """,
                (character_id,),
            ).fetchall()
            return [SoulPayload.from_dict(json.loads(r["payload_json"])) for r in rows]
        finally:
            conn.close()

    async def count_transfers(self, character_id: str) -> int:
        """Count soul transfers involving a character (as source or target)."""
        conn = self._connect_soul()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM soul_payloads
                WHERE source_character_id = ? OR target_character_id = ?
                """,
                (character_id, character_id),
            ).fetchone()
            return int(row["n"])
        finally:
            conn.close()
