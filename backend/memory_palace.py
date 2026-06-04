"""
Memory Palace (Phase A: SQLite + JSON)
======================================
Long-term character memory system for OpenClaw Sandbox RPG.

Phase A scope (per docs/WAVE2_MEMORY_PALACE.md):
  - SQLite storage (zero extra deps beyond aiosqlite)
  - JSON columns for tags / linked_memories / metadata
  - Text-based search via LIKE (Phase B will add vector embeddings)
  - Salience + decay + access_count tracking
  - Link graph (in-memory for Phase A)

Phase B will add:
  - LanceDB-backed vector embeddings
  - Semantic search via cosine similarity

Phase C will add:
  - PostgreSQL + pgvector for production-scale deployments

The 14 async API methods specified in the design doc are scaffolded here.
For Phase A, the 5 most-critical methods are fully implemented; the other
9 are stubs that raise NotImplementedError with a clear migration message.
"""
from __future__ import annotations

import enum
import json
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

UTC = timezone.utc

# ============================================
# Enums (locked contract from WAVE2 design)
# ============================================


class MemoryType(str, enum.Enum):
    """
    Cognition dimension — how the memory is recalled.
    Orthogonal to MemorySource.
    """

    EPISODIC = "episodic"      # Specific events that happened at a time/place
    SEMANTIC = "semantic"      # Facts, world rules, NPC names, relationships
    PROCEDURAL = "procedural"  # Skills, how to do things, decryption steps
    EMOTIONAL = "emotional"    # Significant emotional state changes


class MemorySource(str, enum.Enum):
    """
    Acquisition channel — how the memory was acquired.
    Orthogonal to MemoryType.
    """

    SCENE = "scene"             # Scene context description
    CHOICE = "choice"           # Player decision branch
    NPC_DIALOGUE = "npc_dialogue"  # Conversation with an NPC
    WORLD_EVENT = "world_event" # System-level or environmental event


# Allowed set per source → sanity check (defense against future bug)
ALLOWED_SOURCES: Set[str] = {s.value for s in MemorySource}
ALLOWED_TYPES: Set[str] = {t.value for t in MemoryType}


# ============================================
# Pydantic-compatible dataclass schema
# ============================================


@dataclass
class MemoryFragment:
    """
    A single memory entry. All 12 core fields from the design doc.

    This is a dataclass (not pydantic.BaseModel) to keep Phase A deps-free.
    Validation is done via __post_init__.
    """

    id: str
    character_id: str
    memory_type: MemoryType
    content: str
    source: MemorySource
    salience: float
    created_at: str
    last_accessed_at: str
    access_count: int
    tags: List[str] = field(default_factory=list)
    linked_memories: List[str] = field(default_factory=list)
    decay_rate: float = 0.05
    metadata: Dict[str, Any] = field(default_factory=dict)
    archived: bool = False

    def __post_init__(self) -> None:
        # Validate enums
        if isinstance(self.memory_type, str):
            self.memory_type = MemoryType(self.memory_type)
        if isinstance(self.source, str):
            self.source = MemorySource(self.source)
        # Validate salience in [0, 1]
        if not 0.0 <= self.salience <= 1.0:
            raise ValueError(
                f"salience must be in [0, 1], got {self.salience}"
            )
        # Validate decay_rate in [0, 1]
        if not 0.0 <= self.decay_rate <= 1.0:
            raise ValueError(
                f"decay_rate must be in [0, 1], got {self.decay_rate}"
            )
        if self.access_count < 0:
            raise ValueError(
                f"access_count must be >= 0, got {self.access_count}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict (for JSON storage)."""
        d = asdict(self)
        d["memory_type"] = self.memory_type.value
        d["source"] = self.source.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryFragment":
        """Deserialize from dict (for JSON storage)."""
        d = dict(data)
        d["memory_type"] = MemoryType(d["memory_type"])
        d["source"] = MemorySource(d["source"])
        return cls(**d)


# ============================================
# SQLite Storage Layer
# ============================================


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    memory_type TEXT NOT NULL CHECK (memory_type IN ('episodic','semantic','procedural','emotional')),
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    salience REAL NOT NULL CHECK (salience >= 0.0 AND salience <= 1.0),
    created_at TEXT NOT NULL,
    last_accessed_at TEXT NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    tags_json TEXT NOT NULL DEFAULT '[]',
    linked_memories_json TEXT NOT NULL DEFAULT '[]',
    decay_rate REAL NOT NULL DEFAULT 0.05,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_memory_character ON memory_entries (character_id);
CREATE INDEX IF NOT EXISTS idx_memory_character_active ON memory_entries (character_id, archived);
CREATE INDEX IF NOT EXISTS idx_memory_salience ON memory_entries (character_id, salience DESC) WHERE archived = 0;
"""


def _now_iso() -> str:
    """ISO 8601 timestamp with Z suffix (UTC)."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _row_to_fragment(row: sqlite3.Row) -> MemoryFragment:
    """Convert a SQLite row to MemoryFragment."""
    return MemoryFragment(
        id=row["id"],
        character_id=row["character_id"],
        memory_type=row["memory_type"],
        content=row["content"],
        source=row["source"],
        salience=row["salience"],
        created_at=row["created_at"],
        last_accessed_at=row["last_accessed_at"],
        access_count=row["access_count"],
        tags=json.loads(row["tags_json"]),
        linked_memories=json.loads(row["linked_memories_json"]),
        decay_rate=row["decay_rate"],
        metadata=json.loads(row["metadata_json"]),
        archived=bool(row["archived"]),
    )


# ============================================
# MemoryPalace Class
# ============================================


class MemoryPalace:
    """
    Per-character long-term memory store.

    Phase A: SQLite-backed (single file per character, or shared).
    Phase B: Add LanceDB vector index alongside.
    Phase C: Migrate to pgvector for production.

    All operations are scoped to a single character_id.
    The class is thread-safe via a per-instance lock.
    """

    def __init__(self, db_path: str | os.PathLike):
        self.db_path = str(db_path)
        self._lock: Optional[Any] = None  # lazily initialized in async context
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize_storage()

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def initialize_storage(self) -> None:
        """
        Create the memory_entries table if it doesn't exist.
        Idempotent — safe to call multiple times.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(SQLITE_SCHEMA)
            conn.commit()
            logger.info(f"MemoryPalace storage initialized at {self.db_path}")
        finally:
            conn.close()

    async def _get_lock(self) -> Any:
        """Lazy-init asyncio.Lock (must be created in async context)."""
        import asyncio
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection with row factory enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Phase A: 5 core methods (fully implemented)
    # ------------------------------------------------------------------

    async def add_memory(
        self,
        character_id: str,
        content: str,
        memory_type: MemoryType | str,
        source: MemorySource | str,
        salience: float = 0.5,
        tags: Optional[List[str]] = None,
        decay_rate: float = 0.05,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Add a new memory fragment to the palace.

        Returns the generated memory ID (UUID).
        """
        memory_id = str(uuid.uuid4())
        now = _now_iso()
        fragment = MemoryFragment(
            id=memory_id,
            character_id=character_id,
            memory_type=memory_type,
            content=content,
            source=source,
            salience=salience,
            created_at=now,
            last_accessed_at=now,
            access_count=0,
            tags=tags or [],
            linked_memories=[],
            decay_rate=decay_rate,
            metadata=metadata or {},
        )

        lock = await self._get_lock()
        async with lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO memory_entries
                    (id, character_id, memory_type, content, source,
                     salience, created_at, last_accessed_at, access_count,
                     tags_json, linked_memories_json, decay_rate,
                     metadata_json, archived)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fragment.id,
                        fragment.character_id,
                        fragment.memory_type.value,
                        fragment.content,
                        fragment.source.value,
                        fragment.salience,
                        fragment.created_at,
                        fragment.last_accessed_at,
                        fragment.access_count,
                        json.dumps(fragment.tags),
                        json.dumps(fragment.linked_memories),
                        fragment.decay_rate,
                        json.dumps(fragment.metadata),
                        0,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        return memory_id

    async def get_memories(
        self,
        character_id: str,
        limit: int = 50,
        memory_type: Optional[MemoryType | str] = None,
        min_salience: Optional[float] = None,
        include_archived: bool = False,
    ) -> List[MemoryFragment]:
        """
        Retrieve memories for a character, sorted by salience (desc).

        Optional filters: memory_type, min_salience, include_archived.
        """
        if limit < 1:
            raise ValueError("limit must be >= 1")

        where = ["character_id = ?"]
        params: List[Any] = [character_id]

        if not include_archived:
            where.append("archived = 0")
        if memory_type is not None:
            mt = memory_type.value if isinstance(memory_type, MemoryType) else memory_type
            where.append("memory_type = ?")
            params.append(mt)
        if min_salience is not None:
            where.append("salience >= ?")
            params.append(min_salience)

        query = f"""
            SELECT * FROM memory_entries
            WHERE {' AND '.join(where)}
            ORDER BY salience DESC, last_accessed_at DESC
            LIMIT ?
        """
        params.append(limit)

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
            return [_row_to_fragment(r) for r in rows]
        finally:
            conn.close()

    async def get_memory(self, memory_id: str) -> Optional[MemoryFragment]:
        """
        Retrieve a single memory by ID, incrementing its access count.
        Returns None if not found.

        Uses SQLite RETURNING clause (3.35+) so the returned fragment
        reflects the post-increment access_count atomically.
        """
        lock = await self._get_lock()
        async with lock:
            conn = self._connect()
            try:
                now = _now_iso()
                cursor = conn.execute(
                    """
                    UPDATE memory_entries
                    SET access_count = access_count + 1,
                        last_accessed_at = ?
                    WHERE id = ?
                    RETURNING *
                    """,
                    (now, memory_id),
                )
                row = cursor.fetchone()
                conn.commit()
                if row is None:
                    return None
                return _row_to_fragment(row)
            finally:
                conn.close()

    async def search_keyword(
        self,
        character_id: str,
        query_text: str,
        top_k: int = 10,
    ) -> List[MemoryFragment]:
        """
        Phase A keyword search: SQL LIKE on content + tags.
        Returns memories containing the query text, sorted by salience.

        Phase B will replace this with vector semantic search.
        """
        if not query_text:
            return []
        if top_k < 1:
            raise ValueError("top_k must be >= 1")

        like_pattern = f"%{query_text}%"
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM memory_entries
                WHERE character_id = ?
                  AND archived = 0
                  AND (content LIKE ? OR tags_json LIKE ?)
                ORDER BY salience DESC, last_accessed_at DESC
                LIMIT ?
                """,
                (character_id, like_pattern, like_pattern, top_k),
            ).fetchall()
            return [_row_to_fragment(r) for r in rows]
        finally:
            conn.close()

    async def count(
        self, character_id: str, include_archived: bool = False
    ) -> int:
        """Return the number of memories for a character."""
        conn = self._connect()
        try:
            if include_archived:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM memory_entries WHERE character_id = ?",
                    (character_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM memory_entries WHERE character_id = ? AND archived = 0",
                    (character_id,),
                ).fetchone()
            return int(row["n"])
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Phase B/C: 9 remaining methods (stubs for now)
    # ------------------------------------------------------------------

    async def search_semantic(
        self,
        character_id: str,
        query: str,
        top_k: int = 5,
    ) -> List[MemoryFragment]:
        """
        Semantic search via vector embeddings.

        Phase A: Not implemented. Falls back to search_keyword for now.
        Phase B: Will use LanceDB for vector search.
        """
        logger.warning(
            "search_semantic: not implemented in Phase A, falling back to search_keyword"
        )
        return await self.search_keyword(character_id, query, top_k=top_k)

    async def link_memories(
        self,
        memory_id_1: str,
        memory_id_2: str,
        link_type: str = "related",
    ) -> bool:
        """
        Create a graph relationship between two memories.
        Phase A: appends to linked_memories list.
        Phase B: dedicated edge table.
        """
        if memory_id_1 == memory_id_2:
            return False

        lock = await self._get_lock()
        async with lock:
            conn = self._connect()
            try:
                row1 = conn.execute(
                    "SELECT linked_memories_json FROM memory_entries WHERE id = ?",
                    (memory_id_1,),
                ).fetchone()
                row2 = conn.execute(
                    "SELECT linked_memories_json FROM memory_entries WHERE id = ?",
                    (memory_id_2,),
                ).fetchone()
                if row1 is None or row2 is None:
                    return False
                links1 = json.loads(row1["linked_memories_json"])
                links2 = json.loads(row2["linked_memories_json"])
                if memory_id_2 not in links1:
                    links1.append(memory_id_2)
                if memory_id_1 not in links2:
                    links2.append(memory_id_1)
                conn.execute(
                    "UPDATE memory_entries SET linked_memories_json = ? WHERE id = ?",
                    (json.dumps(links1), memory_id_1),
                )
                conn.execute(
                    "UPDATE memory_entries SET linked_memories_json = ? WHERE id = ?",
                    (json.dumps(links2), memory_id_2),
                )
                conn.commit()
                return True
            finally:
                conn.close()

    async def update_salience(
        self, memory_id: str, new_salience: float
    ) -> bool:
        """Update the salience score of a single memory."""
        if not 0.0 <= new_salience <= 1.0:
            raise ValueError("new_salience must be in [0, 1]")
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE memory_entries SET salience = ? WHERE id = ?",
                (new_salience, memory_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    async def traverse_links(
        self, memory_id: str, max_depth: int = 3
    ) -> List[MemoryFragment]:
        """
        BFS traversal of the memory graph starting from memory_id.
        Returns all reachable memories (excluding the start).
        """
        if max_depth < 0:
            raise ValueError("max_depth must be >= 0")

        visited: Set[str] = set()
        frontier: List[tuple] = [(memory_id, 0)]
        result_ids: List[str] = []

        while frontier:
            current_id, depth = frontier.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)
            if depth >= max_depth:
                continue
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT linked_memories_json FROM memory_entries WHERE id = ?",
                    (current_id,),
                ).fetchone()
            finally:
                conn.close()
            if row is None:
                continue
            links = json.loads(row["linked_memories_json"])
            for linked_id in links:
                if linked_id not in visited:
                    frontier.append((linked_id, depth + 1))
                    if depth + 1 <= max_depth and linked_id != memory_id:
                        result_ids.append(linked_id)

        if not result_ids:
            return []
        placeholders = ",".join("?" * len(result_ids))
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM memory_entries WHERE id IN ({placeholders})",
                result_ids,
            ).fetchall()
            return [_row_to_fragment(r) for r in rows]
        finally:
            conn.close()

    async def apply_decay(
        self, character_id: str, days_elapsed: float = 1.0
    ) -> int:
        """
        Apply time-based decay to all memories for a character.
        Returns the number of memories whose salience was modified.

        decay formula: new_salience = max(0, salience - decay_rate * days_elapsed)
        """
        if days_elapsed < 0:
            raise ValueError("days_elapsed must be >= 0")

        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, salience, decay_rate FROM memory_entries WHERE character_id = ? AND archived = 0",
                (character_id,),
            ).fetchall()
            updated = 0
            for row in rows:
                new_sal = max(0.0, row["salience"] - row["decay_rate"] * days_elapsed)
                if new_sal != row["salience"]:
                    conn.execute(
                        "UPDATE memory_entries SET salience = ? WHERE id = ?",
                        (new_sal, row["id"]),
                    )
                    updated += 1
            conn.commit()
            return updated
        finally:
            conn.close()

    async def consolidate_memories(
        self, character_id: str, similarity_threshold: float = 0.92
    ) -> int:
        """
        Merge near-duplicate memories. Phase A: simple keyword overlap.
        Phase B: will use embedding similarity.
        """
        logger.warning(
            "consolidate_memories: Phase A uses simple overlap; "
            "Phase B will use vector similarity"
        )
        memories = await self.get_memories(character_id, limit=1000)
        if len(memories) < 2:
            return 0
        # Simple word-overlap similarity
        def words(s: str) -> Set[str]:
            return set(s.lower().split())
        merged = 0
        skip: Set[str] = set()
        for i, m1 in enumerate(memories):
            if m1.id in skip:
                continue
            w1 = words(m1.content)
            for m2 in memories[i + 1 :]:
                if m2.id in skip:
                    continue
                w2 = words(m2.content)
                if not w1 or not w2:
                    continue
                overlap = len(w1 & w2) / max(len(w1), len(w2))
                if overlap >= similarity_threshold:
                    # Archive the lower-salience one
                    weaker = m1 if m1.salience < m2.salience else m2
                    conn = self._connect()
                    try:
                        conn.execute(
                            "UPDATE memory_entries SET archived = 1 WHERE id = ?",
                            (weaker.id,),
                        )
                        conn.commit()
                    finally:
                        conn.close()
                    skip.add(weaker.id)
                    merged += 1
        return merged

    async def archive_cold_memories(
        self, character_id: str, salience_floor: float = 0.05
    ) -> int:
        """Archive memories whose salience has decayed below the floor."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE memory_entries SET archived = 1 WHERE character_id = ? AND archived = 0 AND salience < ?",
                (character_id, salience_floor),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    async def transfer_memories(
        self,
        source_character_id: str,
        target_character_id: str,
        preservation_rate: float = 0.7,
    ) -> int:
        """
        Transfer memories from one character to another (Soul Transfer use case).
        Per design doc: episodic sampled, semantic+procedural always kept.
        Returns the number of memories transferred.
        """
        if not 0.0 <= preservation_rate <= 1.0:
            raise ValueError("preservation_rate must be in [0, 1]")
        if source_character_id == target_character_id:
            return 0

        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM memory_entries WHERE character_id = ? AND archived = 0",
                (source_character_id,),
            ).fetchall()
        finally:
            conn.close()

        transferred = 0
        import random
        for row in rows:
            mt = row["memory_type"]
            # semantic + procedural always keep; episodic sampled
            if mt in ("semantic", "procedural"):
                keep = True
            else:  # episodic, emotional
                keep = random.random() < preservation_rate
            if not keep:
                continue

            new_id = str(uuid.uuid4())
            now = _now_iso()
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO memory_entries
                    (id, character_id, memory_type, content, source,
                     salience, created_at, last_accessed_at, access_count,
                     tags_json, linked_memories_json, decay_rate,
                     metadata_json, archived)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id,
                        target_character_id,
                        mt,
                        row["content"],
                        "world_event",  # mark as world event since transferred
                        row["salience"] * 0.8,  # slight salience loss on transfer
                        now,
                        now,
                        0,
                        row["tags_json"],
                        "[]",  # reset links (old IDs no longer valid)
                        row["decay_rate"],
                        json.dumps({**(json.loads(row["metadata_json"])), "transferred_from": source_character_id}),
                        0,
                    ),
                )
                conn.commit()
                transferred += 1
            finally:
                conn.close()
        return transferred

    async def export_state(self, character_id: str) -> Dict[str, Any]:
        """Export all memories for a character as a JSON-serializable dict."""
        memories = await self.get_memories(character_id, limit=10000, include_archived=True)
        return {
            "character_id": character_id,
            "exported_at": _now_iso(),
            "total_count": len(memories),
            "memories": [m.to_dict() for m in memories],
        }
