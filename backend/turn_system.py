"""
Async Turn System (Wave 2 Core #3a)
====================================
Non-blocking turn-based system for multi-player RPG.
Implements per-character turn queue with DB row lock (Q1 = B).

Design lock (2026-06-04):
  - Q1: DB row lock via UPDATE ... WHERE turn_id = ? RETURNING ...
  - Non-blocking: callers can submit and poll later
  - Per-character FIFO order
  - Concurrent-safe: only one turn per character active at any time

Storage:
  - turns table (per character turn queue)
  - turn_states table (current active turn)
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

UTC = UTC


class TurnStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


TURN_SCHEMA = """
CREATE TABLE IF NOT EXISTS turn_states (
    character_id TEXT PRIMARY KEY,
    active_turn_id TEXT,
    turn_locked_until TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS turns (
    turn_id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'completed', 'expired')),
    player_input_json TEXT NOT NULL DEFAULT '{}',
    scene_output_json TEXT NOT NULL DEFAULT '{}',
    submitted_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    deadline TEXT
);

CREATE INDEX IF NOT EXISTS idx_turns_character_pending
    ON turns (character_id, status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_turns_status_deadline
    ON turns (status, deadline);
"""


@dataclass
class Turn:
    turn_id: str
    character_id: str
    round_number: int
    status: TurnStatus
    submitted_at: str
    player_input: dict[str, Any] = field(default_factory=dict)
    scene_output: dict[str, Any] = field(default_factory=dict)
    started_at: str | None = None
    completed_at: str | None = None
    deadline: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


class TurnSystem:
    """
    Per-character turn queue with DB row lock for atomicity.
    """

    def __init__(self, db_path: str | os.PathLike):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize_storage()

    def _initialize_storage(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(TURN_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    async def submit_turn(
        self,
        character_id: str,
        player_input: dict[str, Any],
        deadline_seconds: int = 900,  # 15-min default
    ) -> str:
        """
        Submit a player action for a turn. Returns the turn_id.
        The turn is queued (status=pending) and will be picked up by
        the next call to advance_turn().
        """
        turn_id = str(uuid.uuid4())
        now = _now_iso()
        from datetime import timedelta

        deadline = (
            (datetime.now(UTC) + timedelta(seconds=deadline_seconds))
            .isoformat()
            .replace("+00:00", "Z")
        )

        # Determine round number: max(round_number) + 1, or 1
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT MAX(round_number) AS r FROM turns WHERE character_id = ?",
                (character_id,),
            ).fetchone()
            next_round = (row["r"] or 0) + 1
            conn.execute(
                """
                INSERT INTO turns
                (turn_id, character_id, round_number, status,
                 player_input_json, submitted_at, deadline)
                VALUES (?, ?, ?, 'pending', ?, ?, ?)
                """,
                (turn_id, character_id, next_round, json.dumps(player_input), now, deadline),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return turn_id

    async def advance_turn(
        self,
        character_id: str,
    ) -> Turn | None:
        """
        Atomically claim and activate the next pending turn for a
        character. Uses DB row lock (UPDATE ... RETURNING) so only
        one caller wins.

        Returns the activated Turn, or None if no pending turn.
        """
        conn = self._connect()
        try:
            now = _now_iso()
            # Atomic claim: take the oldest pending turn and mark it active
            cursor = conn.execute(
                """
                UPDATE turns
                SET status = 'active', started_at = ?
                WHERE turn_id = (
                    SELECT turn_id FROM turns
                    WHERE character_id = ? AND status = 'pending'
                    ORDER BY submitted_at ASC
                    LIMIT 1
                )
                RETURNING *
                """,
                (now, character_id),
            )
            row = cursor.fetchone()
            if row is None:
                conn.commit()
                return None
            # Also write the lock marker
            conn.execute(
                """
                INSERT INTO turn_states (character_id, active_turn_id, turn_locked_until, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(character_id) DO UPDATE SET
                    active_turn_id = excluded.active_turn_id,
                    turn_locked_until = excluded.turn_locked_until,
                    updated_at = excluded.updated_at
                """,
                (character_id, row["turn_id"], row["deadline"], now),
            )
            conn.commit()
            return self._row_to_turn(row)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def complete_turn(
        self,
        turn_id: str,
        scene_output: dict[str, Any],
    ) -> bool:
        """
        Mark a turn as completed with its scene output.
        Atomic update to prevent double-completion.
        """
        now = _now_iso()
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                UPDATE turns
                SET status = 'completed', completed_at = ?, scene_output_json = ?
                WHERE turn_id = ? AND status = 'active'
                """,
                (now, json.dumps(scene_output), turn_id),
            )
            # Also clear the active state
            conn.execute(
                """
                UPDATE turn_states
                SET active_turn_id = NULL, turn_locked_until = NULL, updated_at = ?
                WHERE active_turn_id = ?
                """,
                (now, turn_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def expire_overdue_turns(self) -> int:
        """
        Mark all pending turns past their deadline as expired.
        Returns the count of expired turns.
        """
        now = _now_iso()
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                UPDATE turns SET status = 'expired'
                WHERE status = 'pending' AND deadline IS NOT NULL AND deadline < ?
                """,
                (now,),
            )
            conn.commit()
            return cursor.rowcount
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def get_turn(self, turn_id: str) -> Turn | None:
        """Retrieve a single turn by ID."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM turns WHERE turn_id = ?", (turn_id,)).fetchone()
            return self._row_to_turn(row) if row else None
        finally:
            conn.close()

    async def get_pending_count(self, character_id: str) -> int:
        """Get the number of pending turns for a character."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM turns WHERE character_id = ? AND status = 'pending'",
                (character_id,),
            ).fetchone()
            return int(row["n"])
        finally:
            conn.close()

    async def get_active_turn(self, character_id: str) -> Turn | None:
        """Get the currently active turn for a character (if any)."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM turns WHERE character_id = ? AND status = 'active'",
                (character_id,),
            ).fetchone()
            return self._row_to_turn(row) if row else None
        finally:
            conn.close()

    def _row_to_turn(self, row: sqlite3.Row) -> Turn:
        return Turn(
            turn_id=row["turn_id"],
            character_id=row["character_id"],
            round_number=row["round_number"],
            status=TurnStatus(row["status"]),
            submitted_at=row["submitted_at"],
            player_input=json.loads(row["player_input_json"]) if row["player_input_json"] else {},
            scene_output=json.loads(row["scene_output_json"]) if row["scene_output_json"] else {},
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            deadline=row["deadline"],
        )
