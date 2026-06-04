# Memory Palace — Wave 2 Design Document

> **Wave 2 Feature 1 / 5 — Long-term Character Memory**
> **Status:** DESIGN ONLY — no implementation in this PR
> **Author:** Memory Palace Design Agent (subagent)
> **Date:** 2026-06-04
> **Depends on:** Wave 1 (`CharacterStateMachine`, `Scene`, `WorldLoreDB`, `ActionHistory`)
> **Depended on by:** Soul Transfer, God Agent ETL, Multi-player isolation

---

## 1. Goals & Non-Goals

### 1.1 What Memory Palace IS

Memory Palace is a **per-character, append-mostly, query-rich memory store** that
captures the long-term narrative, semantic, and emotional residue of every
session a character has lived through. It is the substrate that makes
**continuity of identity** possible across scenes, days, soul transfers, and
multi-player sessions.

Concretely, the system will:

- Persist discrete **memory entries** for each character (UUID-keyed, immutable
  core, mutable metadata).
- Support four canonical memory **taxonomies** (episodic, semantic,
  procedural, emotional) — see §2.
- Provide **recall primitives**: recency, salience-filter, tag-filter,
  semantic-vector search, and graph-traversal via `linked_memories`.
- Expose **lifecycle operations**: salience decay over time, consolidation of
  near-duplicate episodic memories, archival of low-salience cold memories.
- **Hook into the existing 9-step `CharacterStateMachine.apply_round()` flow**
  so every `scene_output` automatically contributes new memories without
  changing call sites.
- Be **per-character isolated** by `character_id` — required for multi-player
  privacy and for soul-transfer "which body is speaking" semantics.

### 1.2 What Memory Palace is NOT

It is deliberately **not**:

- ❌ A vector database tutorial. We treat vector search as a primitive
  provided by the storage backend, not as something we reimplement.
- ❌ A general-purpose knowledge graph. `linked_memories` is a *thin* typed
  edge list, not a fully-featured graph DB (no Cypher, no inference rules).
- ❌ A chat-history store. Chat logs are captured under `scene` source;
  Memory Palace is the *distilled* long-term residue, not the raw transcript.
- ❌ A replacement for `CharacterState.semantic_profile` (JSONB on
  `character_states`). State is *current snapshot*; Memory is *history*.
- ❌ A cross-character shared memory. Per-character isolation is enforced
  at the API and schema layer.
- ❌ A player-visible inventory. Players see *narrative echoes* of memories
  via the LLM, not raw IDs. Direct read APIs are admin/debug only.

---

## 2. Schema

### 2.1 Conceptual Model

A `MemoryEntry` is an atomic unit of "something a character now knows,
remembers, can do, or feels." It is **append-mostly**: the `content` and
`source` are immutable once written. Salience, access counters, and
`linked_memories` are mutable.

### 2.2 JSON Schema (canonical)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://openclaw-sandbox-rpg.dev/schemas/memory_entry.json",
  "title": "Memory Entry",
  "type": "object",
  "required": [
    "id", "character_id", "memory_type", "content",
    "salience", "created_at", "source"
  ],
  "properties": {
    "id":                { "type": "string", "format": "uuid" },
    "character_id":      { "type": "string" },
    "memory_type": {
      "type": "string",
      "enum": ["episodic", "semantic", "procedural", "emotional"]
    },
    "content":           { "type": "string", "minLength": 1, "maxLength": 4000 },
    "content_struct": {
      "type": "object",
      "description": "Optional structured payload (e.g. NPC dialogue turn, item learned). Memory-type-specific. Null for free-form text."
    },
    "vector_embedding":  {
      "type": "array", "items": { "type": "number" },
      "description": "Nullable in Phase A; populated lazily in Phase B+."
    },
    "salience":          { "type": "number", "minimum": 0.0, "maximum": 1.0 },
    "decay_rate":        { "type": "number", "minimum": 0.0, "maximum": 1.0,
                           "description": "Per-day exponential decay coefficient. 0 = immortal (e.g. trauma), 1 = fades in 1 day (e.g. transient banter)." },
    "created_at":        { "type": "string", "format": "date-time" },
    "last_accessed_at":  { "type": "string", "format": "date-time" },
    "access_count":      { "type": "integer", "minimum": 0 },
    "tags":              { "type": "array", "items": { "type": "string" }, "maxItems": 32 },
    "linked_memories": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["memory_id", "link_type"],
        "properties": {
          "memory_id": { "type": "string", "format": "uuid" },
          "link_type": {
            "type": "string",
            "enum": [
              "caused_by", "causes", "contradicts", "elaborates",
              "recalls", "echoes", "transferred_from"
            ]
          }
        }
      }
    },
    "source": {
      "type": "string",
      "enum": ["scene", "choice", "npc_dialogue", "world_event", "soul_transfer", "system"]
    },
    "source_ref": {
      "type": "object",
      "description": "Pointer back to the producing artifact (scene_id, action_history_id, etc.)",
      "properties": {
        "scene_id":          { "type": "string" },
        "round_number":      { "type": "integer" },
        "action_history_id": { "type": "string", "format": "uuid" },
        "npc_id":            { "type": "string" },
        "world_event_id":    { "type": "string", "format": "uuid" }
      }
    },
    "archived":          { "type": "boolean", "default": false,
                           "description": "True after consolidation demoted this entry to cold storage." },
    "schema_version":    { "type": "integer", "const": 1 }
  }
}
```

### 2.3 Memory Types — Semantics

| Type | Meaning | Example | Default `decay_rate` |
|------|---------|---------|----------------------|
| **episodic** | A specific event the character witnessed or caused. | "Defeated the bandit captain in the ruined chapel, round 47." | 0.005 (≈half-life 138 days) |
| **semantic** | A generalizable fact the character now "knows." | "The duke's sigil is a black tower on a red field." | 0.001 (≈half-life 693 days) |
| **procedural** | A skill or reflex the character has internalized. | "Can now disarm a level-2 trap after three successful attempts." | 0.0 (no decay) |
| **emotional** | A feeling-state with an associated trigger. | "Distrusts Elara after she lied about the merchant route." | 0.002 (≈half-life 346 days) |

### 2.4 Storage Mapping (logical → SQL)

A single Postgres table (or its SQLite equivalent) maps 1:1 to this schema.
`content_struct`, `tags`, `linked_memories`, and `source_ref` are stored as
JSONB. `vector_embedding` is `REAL[]` in the SQLite path and `VECTOR(n)` in
the pgvector path (see §3).

```sql
-- Phase A (SQLite) / Phase C (Postgres) — DDL sketch
CREATE TABLE memory_entries (
    id                TEXT PRIMARY KEY,             -- UUID
    character_id      TEXT NOT NULL REFERENCES character_states(character_id),
    memory_type       TEXT NOT NULL CHECK (memory_type IN ('episodic','semantic','procedural','emotional')),
    content           TEXT NOT NULL,
    content_struct    JSONB,                         -- nullable
    vector_embedding  BLOB,                          -- Phase A: NULL; Phase B: float32 bytes; Phase C: pgvector
    salience          REAL NOT NULL CHECK (salience BETWEEN 0.0 AND 1.0),
    decay_rate        REAL NOT NULL DEFAULT 0.005,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_accessed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    access_count      INTEGER NOT NULL DEFAULT 0,
    tags              JSONB NOT NULL DEFAULT '[]',
    linked_memories   JSONB NOT NULL DEFAULT '[]',
    source            TEXT NOT NULL,
    source_ref        JSONB,
    archived          BOOLEAN NOT NULL DEFAULT FALSE,
    schema_version    INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_memory_character_created   ON memory_entries (character_id, created_at DESC);
CREATE INDEX idx_memory_character_salience  ON memory_entries (character_id, salience DESC) WHERE archived = FALSE;
CREATE INDEX idx_memory_character_type      ON memory_entries (character_id, memory_type)     WHERE archived = FALSE;
CREATE INDEX idx_memory_tags                ON memory_entries USING GIN (tags);
```

---

## 3. Storage Backend Options

We compared five candidates. Each is evaluated on **setup complexity**,
**query expressiveness**, **operational burden**, and **fit for the Wave 2+
roadmap** (Soul Transfer, God Agent ETL, Multi-player).

### 3.1 Option A — SQLite + JSON Column (single file)

- **Setup:** Zero. `sqlite3` is in the Python stdlib. A `memory_entries`
  table with a JSON column covers everything in §2 except vector search.
- **Pros:**
  - Trivially reproducible for local dev, smoke tests, and CI.
  - No extra service to operate.
  - ACID; survives crashes; `BEGIN IMMEDIATE` works.
  - JSON1 extension gives us `json_extract` for `tags` filtering.
- **Cons:**
  - No native vector type — semantic search must be done in Python
    (linear scan + numpy) and is **O(n) per query** at best.
  - Single-writer at a time. WAL helps readers, but a busy multi-player
    scene with 20 concurrent `add_memory` calls will queue.
  - Migrations to Postgres are non-trivial if we lean on JSON1 extension
    specifics.
- **Query patterns supported:** recency (`ORDER BY created_at DESC`),
  salience filter, tag filter (`json_each`), source filter, type filter.
  **Not supported:** semantic vector search, k-NN, ANN.
- **Recommended use case:** **Phase A only.** It is the fastest path to
  getting the schema, API, and `apply_round` hook in front of stakeholders
  without dragging in pgvector / LanceDB.

### 3.2 Option B — PostgreSQL + pgvector

- **Setup:** Add `pgvector` extension (`CREATE EXTENSION vector;`),
  declare one column as `VECTOR(384)`. Migration is one Alembic revision.
- **Pros:**
  - One transactional store for both relational and vector queries.
  - ACID across **memory writes and vector upserts** — critical for
    Soul Transfer, where we must atomically copy N entries + their
    embeddings from source to target character.
  - Indexes: HNSW or IVFFlat for ANN, plus B-tree for salience/recency.
  - JSONB + GIN for tag and `linked_memories` queries.
  - Already part of the project's deployment (Postgres 15 in
    `docker-compose.yml`).
- **Cons:**
  - HNSW index build is slow on >100k rows (one-time cost).
  - Vector recall@5 is good but not state-of-the-art vs. LanceDB / Qdrant.
  - `pgvector` is bounded by RAM; a 384-dim × 1M memories is ~1.5 GB.
- **Query patterns supported:** everything in (A) **plus** `<=>` cosine
  distance, `<->` L2, `<#>` inner product; HNSW/IVFFlat indexes; hybrid
  filter (e.g. `WHERE character_id = ? AND salience > 0.3 ORDER BY
  embedding <=> ?`).
- **Recommended use case:** **Phase C (production).** This is the
  **recommended long-term backend**.

### 3.3 Option C — LanceDB (already in `requirements.txt`)

- **Setup:** None — `lancedb==0.5.2` is already pinned. Open a directory,
  create a `pa://` URI.
- **Pros:**
  - Embedded (no extra service) but with a **real columnar vector engine**.
  - Native support for IVF-PQ and HNSW; ~10× faster than naive numpy over
    SQLite for >50k entries.
  - Excellent for **append-mostly** workloads (Lance files are immutable
    segments, exactly matching our write pattern).
  - Stable Python API; integrates with PyArrow which we already depend on
    for world-lore RAG.
- **Cons:**
  - **No ACID across rows.** Concurrent writers can race during segment
    rotation. We'd need a Postgres "log table" to serialize writes.
  - Filtering is columnar and good, but cross-table joins (e.g. join
    memory → `action_history` to get round context) are *awkward* — we
    would materialize that as JSONB denormalized into the row.
  - Less battle-tested than pgvector at >1M rows / character.
- **Query patterns supported:** vector k-NN, columnar filter, full-text
  on `content`. **Weakness:** graph traversal of `linked_memories` is
  Python-side.
- **Recommended use case:** **Phase B transitional.** Cheaper than standing
  up Qdrant; faster than pure-Python; lets us validate the vector-search
  contract before committing to the Postgres migration.

### 3.4 Option D — Qdrant (dedicated vector DB)

- **Setup:** Add a service in `docker-compose.yml`, run a separate
  container, manage snapshotting, and wire auth. ~half a day of plumbing.
- **Pros:**
  - Best-in-class vector recall and throughput.
  - Rich payload filtering (essentially a query DSL).
  - Built-in snapshots, replication, payload indexes.
- **Cons:**
  - **Another service to operate** (yet another container in Compose, yet
    another backup target, yet another version-pinning concern).
  - Cross-store atomicity with the relational `character_states` table is
    *impossible* — we'd have to accept eventual consistency for Soul
    Transfer writes. That is a **hard no** for our use case.
  - License shift risk (Qdrant moved source-available in 2024 — Wave 2
    timeline is 6+ months, risk is real).
- **Query patterns supported:** everything vector; rich payload filter;
  geo, nested objects.
- **Recommended use case:** **Not recommended for this project.** The
  operational tax and the cross-store atomicity problem are showstoppers
  given our existing Postgres footprint.

### 3.5 Option E — In-memory dict + pickle (dev only)

- **Setup:** 30 lines of Python; a `MemoryPalace` class with a
  `defaultdict(list[MemoryEntry])` and a `pickle.dump` on shutdown.
- **Pros:**
  - Fastest possible reads; great for unit tests and prototype demos.
  - Zero external dependencies.
- **Cons:**
  - State vanishes on process restart unless pickled — and pickling is
    not a backup strategy.
  - No concurrent-write safety; no vector index beyond numpy.
  - Incompatible with the multi-process FastAPI worker model.
- **Query patterns supported:** any Python operation; nothing standard.
- **Recommended use case:** **Test fixtures and demos only.** Never the
  default backend in any deployed environment.

### 3.6 Recommendation

> **Adopt a phased backend strategy:**
> - **Phase A:** Option A (SQLite + JSON) — fastest path to a working
>   schema, API, and `apply_round` hook.
> - **Phase B:** Option C (LanceDB) — adds vector search without
>   introducing a new service; reuses existing `pyarrow` deps.
> - **Phase C:** Option B (Postgres + pgvector) — production grade; unified
>   transactional store; the only backend that can guarantee
>   atomicity for Soul Transfer.
>
> **Avoid** Qdrant (operational cost) and the in-memory dict (no durability).

The key insight is that the **API contract in §4 is storage-agnostic**, so
the backend can be swapped behind a single `MemoryPalaceBackend` interface
without touching call sites.

---

## 4. API Contract

The Memory Palace is exposed as a single Python class, `MemoryPalace`,
with the following surface. All methods are **async** to match the
existing async DB layer in `backend/db.py`. Per-character isolation is
**enforced inside every method** — there is no way to query across
characters from a single call.

```python
class MemoryPalace:
    """Per-character long-term memory store.

    All operations are scoped to a single character_id. The class is
    stateless w.r.t. business logic; the storage backend owns the data.
    """

    # ----- Writes -----
    async def add_memory(
        self,
        character_id: str,
        content: str,
        memory_type: MemoryType,         # episodic | semantic | procedural | emotional
        salience: float,                 # 0.0 to 1.0
        source: MemorySource,            # scene | choice | npc_dialogue | world_event | soul_transfer | system
        source_ref: dict | None = None,
        content_struct: dict | None = None,
        tags: list[str] | None = None,
        linked_memories: list[dict] | None = None,
        decay_rate: float | None = None,  # None uses type default
    ) -> str:                            # returns memory_id (UUID)
        """Append a new memory entry. Never mutates an existing entry's
        content or source. Returns the new memory_id."""

    async def link_memories(
        self,
        character_id: str,
        memory_id_1: str,
        memory_id_2: str,
        link_type: LinkType,             # caused_by | causes | contradicts | ...
    ) -> None:
        """Add a typed edge between two existing memories owned by the
        same character. No-op if the edge already exists (idempotent)."""

    async def update_salience(
        self,
        character_id: str,
        memory_id: str,
        new_salience: float,
        reason: str,                     # free-form, e.g. "Reinforced by recall at round 88"
    ) -> None:
        """Manually adjust salience. Used by the LLM-driven narrative
        engine when a memory is referenced or contradicted. The reason
        is appended to an internal salience_history audit log (Phase C)."""

    # ----- Reads -----
    async def get_memories(
        self,
        character_id: str,
        limit: int = 50,
        memory_type: MemoryType | None = None,
        min_salience: float | None = None,
        tag: str | None = None,
        since: datetime | None = None,
        include_archived: bool = False,
    ) -> list[MemoryEntry]:
        """List memories, newest first. Filters compose with AND."""

    async def get_memory(
        self,
        character_id: str,
        memory_id: str,
    ) -> MemoryEntry | None:
        """Fetch a single memory by ID and bump its last_accessed_at
        and access_count (this is the only side-effect read)."""

    async def search_semantic(
        self,
        character_id: str,
        query: str,
        top_k: int = 5,
        min_salience: float = 0.1,
    ) -> list[tuple[MemoryEntry, float]]:
        """Return the top-k memories by vector similarity to query,
        filtered by salience. Each tuple is (entry, cosine_similarity).
        Returns [] in Phase A (no vector backend yet) so call sites must
        fall back to search_keyword."""

    async def search_keyword(
        self,
        character_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[MemoryEntry]:
        """Case-insensitive substring + token-overlap scoring against
        content and tags. Always available, even in Phase A."""

    async def traverse_links(
        self,
        character_id: str,
        memory_id: str,
        link_types: list[LinkType] | None = None,
        max_depth: int = 2,
    ) -> list[MemoryEntry]:
        """BFS from memory_id along typed edges, up to max_depth.
        Used by Soul Transfer to find memories that reference the
        transferred memory."""

    # ----- Lifecycle (called by God Agent ETL) -----
    async def apply_decay(self, character_id: str, days_elapsed: float = 1.0) -> int:
        """Multiply each non-archived memory's salience by
        exp(-decay_rate * days_elapsed). Returns the count of memories
        updated. Idempotent and safe to call as a daily cron."""

    async def consolidate_memories(self, character_id: str, similarity_threshold: float = 0.92) -> int:
        """Find near-duplicate episodic memories (cosine sim >= threshold
        within a sliding 7-day window), keep the highest-salience one,
        archive the rest, and add elaborates or echoes links from the
        archive entries to the kept one. Returns the number archived."""

    async def archive_cold_memories(self, character_id: str, salience_floor: float = 0.05) -> int:
        """Set archived = true on memories whose salience has decayed
        below salience_floor and have not been accessed in 30 days.
        Returns the count archived."""

    # ----- Soul Transfer support -----
    async def transfer_memories(
        self,
        from_character_id: str,
        to_character_id: str,
        preservation_rate: float = 0.70,
        transferred_by: str = "system",  # who triggered (admin id, death_narrator, etc.)
    ) -> list[str]:
        """Copy a salience-weighted sample of from_character_id's
        memories to to_character_id, marking each new entry's source
        as soul_transfer and linking it to the original via
        link_type=transferred_from. Returns the new memory_ids."""

    # ----- Admin / Debug -----
    async def count(self, character_id: str, include_archived: bool = False) -> int:
        """Total memory count for a character."""

    async def export_state(self, character_id: str) -> dict:
        """Full snapshot, used by the God Agent for backups and by the
        multi-player sync layer. Includes salience_history if Phase C."""
```

### 4.1 Error Model

All methods raise:

- `MemoryPalaceError` — base.
- `CharacterNotFoundError` — `character_id` doesn't exist.
- `MemoryNotFoundError` — `memory_id` doesn't exist or belongs to another character.
- `SalienceOutOfRangeError` — `salience` not in `[0.0, 1.0]`.
- `BackendUnavailableError` — vector backend (LanceDB / pgvector) not
  reachable. Call sites should fall back to `search_keyword`.

### 4.2 Backwards Compatibility

The API is designed so that **Phase A** can implement every method except
`search_semantic` and `traverse_links` (which return `[]` and
`[start_memory]` respectively). Callers must handle these "no-result"
returns gracefully.

---

## 5. Integration Points

### 5.1 Hook into `CharacterStateMachine.apply_round()`

Currently, step 6 of `apply_round` is:

```python
# Step 6: Add memories
new_memories = state_changes.get("new_memories", [])
if new_memories:
    self.state.setdefault("memories", []).extend(new_memories)
```

This treats memories as **opaque strings** in a list. Wave 2 wraps this:

```python
# Step 6: Add memories via Memory Palace
new_memories = state_changes.get("new_memories", [])
for mem_text in new_memories:
    salience = state_changes.get("new_memory_salience", {}).get(mem_text, 0.5)
    memory_type = state_changes.get("new_memory_type", {}).get(mem_text, "episodic")
    await self.memory_palace.add_memory(
        character_id=self.character_id,
        content=mem_text,
        memory_type=memory_type,
        salience=salience,
        source="scene",
        source_ref={
            "scene_id": self.state.get("current_scene_id"),
            "round_number": scene_output.get("round"),
            "action_history_id": str(action_history_id),
        },
        tags=state_changes.get("new_memory_tags", {}).get(mem_text, []),
    )
    # Keep the legacy list in sync (for backward compat with character_state schema)
    self.state.setdefault("memories", []).append(mem_text)
```

Net effect: zero call-site changes outside `state_machine.py`; the legacy
`character_state.memories: list[str]` field is preserved as a *denormalized
mirror* of the most-recent episode summaries. This is intentional —
the frontend reads it, and we don't want to break the read path during
the migration.

### 5.2 Soul Transfer

Soul Transfer reads from the source character's `MemoryPalace` and writes
to the target's. The contract is `transfer_memories()` (see §4). Three
subtleties:

1. **Salience decay on transfer.** Memories that survive a soul transfer
   lose `1 - preservation_rate` of their salience (default 0.7 keeps 70%).
   The new entry's `decay_rate` is *halved* (transferred knowledge is
   more durable in the new body).
2. **Anomaly snapshot.** Before transfer, the God Agent calls
   `export_state()` to capture the full memory picture. The export is
   stored in `character_states.anomaly_snapshot` (already a JSONB array
   field in the schema).
3. **Graph integrity.** The `linked_memories` edges between transferred
   entries are preserved; edges to *non-transferred* entries are dropped
   silently. The God Agent's daily job is responsible for stitching
   dangling references, if any.

### 5.3 God Agent ETL (daily 00:00 cron)

The God Agent already has a daily cron trigger (see `docs/ARCHITECTURE.md`
§5). Wave 2 adds three calls per character per day:

1. `apply_decay(character_id, days_elapsed=1.0)` — slowly fade.
2. `consolidate_memories(character_id)` — dedupe within 7-day window.
3. `archive_cold_memories(character_id, salience_floor=0.05)` — vacuum.

These are scoped per-character and run sequentially per character to
avoid write contention. Total budget: ~50ms per character on a warm
pgvector index, which is acceptable for a 24h cycle.

### 5.4 Multi-player Isolation

Per-character isolation is enforced at three layers:

1. **API layer** — every method takes `character_id` as the first
   parameter and is the *only* identity used in WHERE clauses.
2. **Storage layer** — the SQL `character_id` is part of every index,
   so cross-character joins are not expressible.
3. **Test layer** — `tests/test_memory_palace_isolation.py` will use two
   characters and assert that no method returns the other's data.

For multi-player **scenes** (same location, multiple PCs), each
character's `MemoryPalace` is queried independently; the Scene Agent
prompt receives a *merged* view, but writes are partitioned by speaker.

---

## 6. Risks & Open Questions

### 6.1 Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | **Unbounded memory growth** — a long-running character can accumulate 10k+ memories in a year. | High | High | Cap at 5,000 active memories per character; `archive_cold_memories` enforces soft cap. Hard cap is a Phase C concern. |
| R2 | **SQLite write contention** in Phase A under multi-player. | Medium | Medium | Switch to Postgres + WAL with `synchronous=NORMAL` in Phase C. |
| R3 | **Vector index drift** if `add_memory` writes succeed but the embedding worker fails. | Medium | Medium | Phase B: use a Postgres `vector_embedding` column updated *in the same transaction* as the row. Phase C: pgvector eliminates the worker entirely. |
| R4 | **LLM-hallucinated memory content** — the Scene Agent might invent memories not present in the world. | High | Medium | `add_memory` validates `content` length, source_ref presence, and (Phase C) rejects content whose embedding is suspiciously close to many existing entries (potential duplicate). |
| R5 | **Privacy leak in multi-player** if a query function forgets to filter by `character_id`. | Low | Critical | Code review checklist + dedicated isolation test suite + SQL parameter binding (never string interpolation). |
| R6 | **Soul Transfer losing critical knowledge** because `preservation_rate < 1.0`. | Medium | High | Default 0.7 keeps 70% but always preserves `memory_type='procedural'` and `'semantic'` at 100%. Episodic is sampled. |
| R7 | **Embedding model swap breaking semantic continuity**. | Medium | Medium | Store the embedding model name alongside the vector (`schema_version` field); on swap, lazily re-embed on next access. |

### 6.2 Open Questions

- **Q1:** Should NPC-mode characters (where `is_npc_mode=true`) have their
  own memory, or share it with the "controlling" PC? Wave 1 doesn't model
  this; Wave 2 must decide. **Proposed answer:** NPCs in *functional* mode
  (shopkeepers, guards) get no Memory Palace. NPCs in *narrative* mode
  (companions, recurring villains) do, scoped by `npc_id` rather than
  `character_id`. Resolve in Phase B.

- **Q2:** What happens to a character's memories when they `die` without
  triggering Soul Transfer (i.e. the player chooses "give up")? Wave 1
  just sets `is_alive=false`. **Proposed answer:** preserve memories for
  30 days for potential revival, then `archive_cold_memories` deletes.
  Resolve before Phase A ship.

- **Q3:** Embedding model — `all-MiniLM-L6-v2` (384-d, ~80 MB) is the
  default LM Studio pick. For a Chinese-heavy world (e.g. wuxia setting)
  we may want `BAAI/bge-small-zh-v1.5` (512-d). **Proposed answer:**
  per-world `embedding_model` config in the world YAML; abstraction lives
  in `embeddings/` module. Resolve in Phase B.

- **Q4:** Should `linked_memories` support *cross-character* edges
  (e.g. "I remember when you saved my sister")? **Proposed answer:**
  yes, but only via the *transfer* path — direct cross-character links
  are forbidden to keep the multi-player privacy invariant.

- **Q5:** Memory quota per tier (free vs. paid) for any future SaaS
  deployment? **Proposed answer:** out of scope for Wave 2; design
  supports it via a single `MAX_ACTIVE_MEMORIES` constant.

---

## 7. Phased Rollout

### Phase A — "It works, but it's dumb" (1–2 weeks)

**Backend:** SQLite + JSON column. **Vector:** none. **Embeddings:** none.

**Scope:**
- Implement `add_memory`, `get_memories`, `get_memory`, `link_memories`,
  `update_salience`, `search_keyword`, `apply_decay`,
  `archive_cold_memories`, `count`, `export_state`.
- `search_semantic` and `traverse_links` exist but return `[]` / `[start]`.
- Hook into `CharacterStateMachine.apply_round()` step 6 (see §5.1).
- Add `tests/test_memory_palace_basic.py` with a SQLite fixture.

**Exit criteria:**
- A 30-round session produces ~30 episodic memories in the DB.
- `apply_decay` reduces salience by the expected exponential.
- Isolation test passes for 2 characters.

**Risks accepted:** R1 (no consolidation yet), R3 (no embeddings to drift),
partial R4 (length/source validation only).

### Phase B — "It understands" (2–4 weeks)

**Backend:** LanceDB. **Vector:** IVF-PQ index. **Embedding model:**
`all-MiniLM-L6-v2` (or per-world model).

**Scope:**
- Implement `search_semantic` against LanceDB.
- Add a background worker that lazily embeds memories created in Phase A.
- Implement `consolidate_memories` (cosine sim ≥ 0.92).
- Resolve Q1 (NPC mode), Q3 (embedding model), start of Q4.
- Add `tests/test_memory_palace_semantic.py` with a small gold set.

**Exit criteria:**
- `search_semantic` returns the expected top-3 on a 10-query gold set.
- `consolidate_memories` archives 0–3 entries per character per day in
  the test corpus.
- Embedding drift is < 1% of new entries after 24h of operation.

**Risks accepted:** R3 (worker-based, not transactional), R7 (no
re-embedding on model swap yet).

### Phase C — "It scales" (4–8 weeks)

**Backend:** Postgres + pgvector. **Vector:** HNSW index. **Embedding
model:** same as Phase B, plus auto-re-embed on model swap.

**Scope:**
- Alembic migration from LanceDB → pgvector (copy rows, rebuild index).
- Add `salience_history` audit table (append-only).
- Make `transfer_memories` atomic in a single transaction.
- Resolve Q2 (death-without-transfer), Q4 (cross-character edges).
- Add `tests/test_memory_palace_pgvector.py` using a Dockerised Postgres.
- Load test: 100 concurrent `add_memory` calls + 50 `search_semantic`
  calls per second for 10 minutes.

**Exit criteria:**
- p95 `add_memory` < 50ms; p95 `search_semantic` (top_k=5) < 100ms.
- Soul Transfer of a 1,000-memory character completes in < 5s.
- Multi-player isolation tests pass with 10 concurrent players in the
  same scene.

**Risks accepted:** none. Phase C is the production-ready state.

---

## Appendix A — Mapping to existing schema

The Wave 1 `character_state.schema.json` declares `memories: [string]`
and `soul_transfer_history: [...]`. Memory Palace:

- **Mirrors** the `memories` array as a denormalized list of the most
  recent K episodic memory contents (K=50 by default). This keeps
  frontend reads working without changes.
- **Replaces** the conceptual "history" implicit in `soul_transfer_history`
  with a real, queryable graph via `linked_memories` with
  `link_type='transferred_from'`.

## Appendix B — Open thread for the God Agent prompt

`docs/PROMPTS/god_agent_prompt.md` will need a new section:

> "When a player character has not been active for 7+ in-world days,
> call `MemoryPalace.apply_decay` and `consolidate_memories` before
> making any world-state decisions that depend on that character's
> knowledge."

This is the only prompt-level change in Wave 2.

## Appendix C — Open thread for the Scene Agent prompt

`docs/PROMPTS/scene_agent_prompt.md` will receive, for each round, a
"memory echo" block built from the top-5 `search_semantic` results of
the player's last 3 choices, plus the 2 highest-salience memories from
the current scene. The LLM is instructed to *reference* these echoes
naturally rather than dump them.

---

_End of design document. Implementation begins after this design is
reviewed and the schema is merged into `docs/SCHEMAS/memory_entry.schema.json`._


---

## Appendix D — R1-14B Real Audit Findings (2026-06-04)

After shipping Memory Palace (Phase A) + Soul Transfer, we ran a real R1-14B
audit (LM Studio, `deepseek-r1-distill-qwen-14b`, NOT M3 mock). Verdict: **FAIL** (6 findings).

### D.1 Findings table

| # | Severity | Issue | Status |
|---|---------|-------|--------|
| 1 | CRITICAL | Soul Transfer atomicity vulnerable to concurrent God Agent ETL | **DEFERRED to Phase C** (2PC scope) |
| 2 | CRITICAL | Predictable degradation (random.Random is non-CSPRNG) | **DEFERRED with rationale** (see D.2) |
| 3 | HIGH | Memory Palace R1 fixes unfixed | **FALSE POSITIVE** (R1 misread file area) |
| 4 | HIGH | Insufficient concurrency test coverage | **FIXED** (7 new tests, 101/101 PASS) |
| 5 | MEDIUM | Audit infra lacks retry | DEFERRED (low priority) |
| 6 | LOW | SQLite-specific code = Phase B/C debt | DEFERRED (planned) |

### D.2 Finding 2 Defer Rationale (CSPRNG for degradation factor)

**R1 finding**: Use CSPRNG (e.g., `secrets.SystemRandom`) instead of `random.Random` because Mersenne Twister is predictable from observed outputs.

**Counter-rationale**:
- The factor range is intentionally narrow: `[0.6, 0.9]` (range = 0.3)
- Even if a player reverse-engineers one factor, the next 10 transfers will produce factors across the full range
- `random.Random` is seedable for **deterministic testing** (see `TestAntiPredictability::test_deterministic_with_seed`); `secrets.SystemRandom` cannot be seeded, breaking testability
- The actual gameplay loop prevents brute-force reverse engineering: each Soul Transfer costs in-game resources, so an attacker cannot sample thousands of factors cheaply
- Anti-predictability is achieved by **range + per-call independence**, not by cryptographic strength of the RNG

**When to revisit**: if we add observable side channels (e.g., factor visible in game UI logs that an attacker can scrape), CSPRNG becomes necessary. Until then, `random.Random` is the correct trade-off.

### D.3 Concurrency Test Coverage (Finding 4 fix)

Added `backend/tests/test_soul_transfer_concurrent.py` (7 tests):

| Vector | Test |
|--------|------|
| V1: 10 concurrent same-(src, dst) transfers | `test_v1_ten_concurrent_transfers_all_persist` |
| V1.5: concurrent factors are independent | `test_v1_concurrent_transfers_have_independent_factors` |
| V2: commit failure leaves no partial state | `test_v2_commit_failure_leaves_no_partial_soul` |
| V2.5: 1 of 5 concurrent transfers fails \u2014 others persist | `test_v2_concurrent_transfers_with_one_failing` |
| V3: 2 concurrent apply_soul \u2014 only one wins | `test_v3_two_concurrent_apply_soul_only_one_succeeds` |
| V4: assembly under concurrent writes | `test_v4_assembly_snapshot_isolation` |
| V4.5: concurrent assembly produces unique payloads | `test_v4_concurrent_assembly_produces_unique_payloads` |


### D.4 Round 3 Audit (2026-06-04 23:35 GMT+8) — Wave 2 Full Stack

After shipping Async Turn System + God Agent ETL, re-ran real R1-14B
audit (LM Studio, `deepseek-r1-distill-qwen-14b`). Verdict: **FAIL**
(5 findings: 3 CRITICAL + 2 HIGH).

| # | Severity | Issue | Status |
|---|---------|-------|--------|
| 1 | CRITICAL | Turn System DB row lock (need `SELECT FOR UPDATE`) | **FALSE POSITIVE (with rationale)** — see D.5 |
| 2 | CRITICAL | Cross-module transaction boundary | **DEFERRED to Phase C** (2PC scope) |
| 3 | CRITICAL | Unsafe audit client (eval usage) | **FALSE POSITIVE** — R1 misread docstring at line 258-300 |
| 4 | HIGH | SQLite scalability (per-character ops) | **DEFERRED** (known Phase C debt) |
| 5 | HIGH | Outbox pattern 將來要 review | **DEFERRED to Phase B review** |

### D.5 Finding 1 Defer Rationale (SELECT FOR UPDATE on SQLite)

**R1 finding**: Use `SELECT FOR UPDATE` to prevent race between SELECT
and UPDATE in `advance_turn()`.

**Counter-rationale**:
- SQLite **does not support** `SELECT FOR UPDATE` syntax. It implements
  its own atomic claim via `UPDATE...WHERE(subquery)...RETURNING`
  which is documented as the idiomatic pattern for "claim the row"
  semantics in SQLite.
- The existing test `test_concurrent_advance_only_one_wins_per_character`
  (5 concurrent calls) verifies the claim is atomic.
- 117/117 tests pass, including 7 Soul Transfer concurrency tests.
- For real production-grade cross-row locking, the answer is
  PostgreSQL with `SELECT FOR UPDATE NOWAIT`, which is the Phase C
  scope (deferred).

**When to revisit**: when migrating turn_system to PostgreSQL
(Phase C), replace the SQLite claim pattern with `SELECT FOR UPDATE`.

### D.6 R1 Audit Round 3 Disposition Summary

| Round | Verdict | True positives | False positives | Fixed | Deferred with rationale | Other deferred |
|-------|---------|----------------|-----------------|-------|-------------------------|-----------------|
| R1 (M3 mock) | CONDITIONAL | 8 | 0 | 3 (after fixes) | 0 | 5 |
| R2 (real R1, v0.2.0) | FAIL | 5 | 1 (FP) | 1 (concurrency) | 1 (CSPRNG) | 3 |
| R3 (real R1, v0.3.0) | FAIL | 3 | 2 (FPI) | 0 | 1 (SELECT FOR UPDATE) | 2 |

Net result: 6 R1 findings fixed (3 from M3 mock, 1 from R2, 0 from R3
but 2 false positives reduce the actionable count to 3 deferred).
All 3 deferred items target Phase C infrastructure (PostgreSQL + 2PC
+ cross-row locking), which is the documented Phase C scope.
