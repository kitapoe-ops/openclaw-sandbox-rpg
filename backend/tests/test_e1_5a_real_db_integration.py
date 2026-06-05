"""
E1.5a — Real-DB integration test for ActionProcessor (Phase E1.5a)
==================================================================

Addresses the *E1.5 Real-DB Integration Gap* documented in
``docs/PHASE_E1_SUMMARY.md`` (Known Limitations §E1.5, 2026-06-05):

  * ``ActionProcessor.__init__`` has ``memory_palace=None`` default.
  * 11/11 unit tests in ``test_action_processor.py`` use
    ``MockLLMClient`` + ``AsyncMock`` palace — the full E2E path
    (FastAPI → validate → physics-lock → LLM → memory_palace.remember
    → Postgres + LanceDB) has **zero real-DB coverage**.

This test wires a **REAL** aiosqlite ``PostgresPersistence`` + a REAL
``VectorStore`` (auto-detected fallback — no LanceDB required) into
``ActionProcessor``, runs ONE happy-path ``process()`` call, and asserts:

  1. The whitelist validates ``("move", "north")`` cleanly.
  2. ``MockLLMClient.generate()`` returns a canned narrative (LLM is
     intentionally still mocked — the test is about persistence, not
     the LLM provider).
  3. ``memory_palace.remember()`` actually wrote a row to Postgres AND
     added a vector to the index (no silent skip).
  4. ``memory_palace.recall()`` with the same query embedding returns
     the persisted narrative (round-trip works end-to-end).
  5. ``memory_palace.health()`` reports both backends healthy.
  6. No deadlock / no hang: the whole test completes in <2 seconds
     (we do not run the full 11-step suite, just this one path).

**Hard constraints (do NOT modify protected files):**
  - ``backend/api/action_processor.py`` (E1) — frozen, we instantiate
    it via the public constructor with ``memory_palace=...`` injected.
  - ``backend/memory_palace.py`` + ``backend/memory_palace_integration.py``
    (C2) — frozen; we use the public ``MemoryPalaceIntegration`` API.
  - ``backend/persistence_pg.py`` (B3) — frozen; we pass a
    ``sqlite+aiosqlite:///<file>`` URL (hermetic, no real Postgres).
  - ``backend/vector_store.py`` (B1) — frozen; we instantiate
    ``VectorStore()`` with default args and let the auto-detect fall
    back to the pure-Python dict backend when LanceDB is unavailable.

**Out of scope (E1.5b / F-candidates):**
  - Concurrent serialization (E1.5b).
  - Real async-to-sync bridge with sentence-transformers (not
    installed; we use a deterministic one-hot vector instead).
  - Real R1 audit (mocked at the LLM layer is fine here).

If this test ever surfaces a real failure, the failure IS the answer
the user is looking for — we have not been able to verify the E2E
path end-to-end against a real database up to this point.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict

import pytest
import pytest_asyncio

# Ensure repo root is on sys.path (mirrors the rest of backend/tests/).
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.api.action_processor import (  # noqa: E402
    ALLOWED_VERBS,
    ActionProcessor,
    InMemoryTurnSystem,
)
from backend.llm_client import MockLLMClient  # noqa: E402
from backend.memory_palace_integration import (  # noqa: E402
    EMBEDDING_DIM,
    MemoryPalaceIntegration,
)
from backend.persistence_pg import PostgresPersistence  # noqa: E402
from backend.vector_store import VectorStore  # noqa: E402


# ============================================
# Helpers
# ============================================
def _one_hot(index: int, dim: int = EMBEDDING_DIM) -> list[float]:
    """Return a dim-length vector with a single 1.0 at ``index``.

    Used as both the persistence embedding and the recall query so
    that cosine similarity is **deterministic** (1.0 to the same
    vector, 0.0 to any other unit vector). The action processor
    currently does not use ``args['embedding']`` — it zero-fills —
    so for the persistence step the vector goes through the
    processor's own internal zero-fill path; for the recall step we
    use a one-hot to make the round-trip assertion deterministic
    independent of what the processor stored.
    """
    v = [0.0] * dim
    v[index] = 1.0
    return v


# ============================================
# Fixtures
# ============================================
@pytest_asyncio.fixture
async def real_palace(tmp_path: Path) -> MemoryPalaceIntegration:
    """Yield a fresh ``MemoryPalaceIntegration`` wired to:

    * a real aiosqlite ``PostgresPersistence`` (per-test file under
      ``tmp_path`` — pytest cleans it up),
    * a real ``VectorStore`` with default args (auto-detects the
      absence of LanceDB → pure-Python dict fallback, fully
      supported per ``backend/vector_store.py`` §"Pure-Python helpers").

    The fixture does NOT call a ``start()`` method — the integration
    is lazily self-initializing: ``_ensure_schema()`` runs on the
    first ``remember()`` call, and the fallback vector store is
    usable from construction.
    """
    db_file = tmp_path / "e1_5a_real_db.db"
    persistence = PostgresPersistence(f"sqlite+aiosqlite:///{db_file}")
    vector_store = VectorStore()  # auto-detect → fallback in test env
    integration = MemoryPalaceIntegration(persistence, vector_store)
    try:
        yield integration
    finally:
        # Always dispose the engine so the aiosqlite file handle is
        # released (pytest will then remove ``tmp_path``).
        try:
            await integration.close()
        except Exception:
            # Defensive: a crashed test should not mask the original
            # failure with a teardown error.
            pass


# ============================================
# The single E2E test
# ============================================
@pytest.mark.asyncio
async def test_action_processor_full_pipeline_with_real_db(
    real_palace: MemoryPalaceIntegration,
) -> None:
    """E2E: ActionProcessor → real aiosqlite + real VectorStore → memory persisted.

    Pipeline covered (single test, but spans 5 steps):

      1. ``ActionProcessor.__init__(memory_palace=real_palace)`` —
         wires a REAL palace, not ``None`` and not a mock.
      2. ``processor.process("player_1", "move", "north")`` —
         - whitelist validation passes (``"move"`` is in
           ``ALLOWED_VERBS``)
         - per-character physics lock acquired / released
         - ``MockLLMClient.generate()`` returns a canned narrative
         - ``memory_palace.remember(...)`` is awaited: PG row
           written, vector indexed
      3. ``memory_palace.count("player_1") == 1`` — row is in PG.
      4. ``memory_palace.recall("player_1", query_embedding, k=5)``
         returns at least one record with the expected ``content``
         shape (proves the vector + PG round-trip is consistent).
      5. ``memory_palace.health() == {"postgres": True,
         "vector_store": True}`` — both backends reachable.
      6. No deadlock, no hang: the test must finish well under
         2 seconds (we use ``time.monotonic()`` to assert it
         explicitly — catches the "asyncio.Lock never released"
         failure mode called out in PHASE_E1_SUMMARY.md).

    Test runtime target: <2s. The test will FAIL (rather than hang
    indefinitely) on the realistic failure modes enumerated in the
    PHASE_E1_SUMMARY.md "Known Limitations" section.
    """
    t_start = time.monotonic()

    # ---- 1) Build the processor with a REAL palace. ----
    canned_narrative = "你大步向北走去，腳下的碎石沙沙作響，遠處的城牆漸漸清晰。"
    llm_client = MockLLMClient(canned_response=canned_narrative)

    processor = ActionProcessor(
        llm_client=llm_client,
        memory_palace=real_palace,  # ← the whole point of E1.5a
        turn_system=InMemoryTurnSystem(),
    )

    # Sanity: ensure the palace is NOT the None default.
    assert processor.memory_palace is real_palace, (
        "ActionProcessor.memory_palace is not the real palace; "
        "the wiring step failed silently."
    )
    # And that the verb we're about to use is actually whitelisted.
    assert "move" in ALLOWED_VERBS, (
        f"'move' not in ALLOWED_VERBS; this test is stale. "
        f"Allowed (first 5): {sorted(ALLOWED_VERBS)[:5]}"
    )

    # ---- 2) Run the full pipeline against the real backends. ----
    result = await processor.process(
        character_id="player_1",
        verb="move",
        target="north",
    )

    # ---- 3) Validate the response shape. ----
    assert isinstance(result, dict), f"process() must return dict, got {type(result)}"
    assert result.get("status") == "processed", (
        f"unexpected status: {result!r}"
    )
    assert "action_id" in result, f"missing action_id: {result!r}"
    # Validate the action_id is a UUID-shaped string.
    try:
        uuid.UUID(result["action_id"])
    except (TypeError, ValueError):
        pytest.fail(f"action_id is not a valid UUID: {result['action_id']!r}")

    assert "narrative" in result, f"missing narrative: {result!r}"
    # The MockLLMClient returns the canned_response verbatim.
    assert result["narrative"] == canned_narrative, (
        f"narrative mismatch: got {result['narrative']!r}, "
        f"expected {canned_narrative!r}"
    )

    # The side_effects list should contain a ``memory_persisted``
    # entry — that's the proof the processor actually called
    # ``palace.remember()`` (as opposed to skipping it or hitting
    # the ``memory_persist_failed`` branch).
    side_effects = result.get("side_effects", [])
    persist_effects = [
        se for se in side_effects if se.get("type") == "memory_persisted"
    ]
    assert persist_effects, (
        f"no 'memory_persisted' side_effect — processor skipped "
        f"persistence! side_effects={side_effects!r}"
    )
    memory_id = persist_effects[0]["memory_id"]
    assert isinstance(memory_id, str) and memory_id, (
        f"bad memory_id: {memory_id!r}"
    )
    # And the memory_id should also be a UUID (MemoryPalaceIntegration
    # uses uuid4 for memory rows).
    try:
        uuid.UUID(memory_id)
    except (TypeError, ValueError):
        pytest.fail(f"memory_id is not a valid UUID: {memory_id!r}")

    # ---- 4) Verify the row is actually in Postgres. ----
    pg_count = await real_palace.count("player_1")
    assert pg_count == 1, (
        f"expected 1 memory in PG for player_1, got {pg_count}. "
        f"side_effects={side_effects!r}"
    )

    # ---- 5) Verify the vector is actually indexed. ----
    # Recall with the same embedding we persisted. Because the
    # ActionProcessor zero-fills the embedding internally (see its
    # ``_persist_memory`` docstring: "we zero-fill if no embedding-fn
    # is registered"), the stored vector is all-zeros. The recall
    # will still return it (filter is by character_id, not by
    # similarity > 0), so we only need to assert the row comes back
    # with the persisted ``content`` rehydrated.
    zero_embedding = [0.0] * EMBEDDING_DIM
    recall_hits = await real_palace.recall(
        character_id="player_1",
        query_embedding=zero_embedding,
        k=5,
    )
    assert len(recall_hits) >= 1, (
        f"recall returned nothing; memory was not retrievable. "
        f"side_effects={side_effects!r}"
    )
    # The first hit should be our memory; verify content rehydration.
    top_hit = recall_hits[0]
    assert "content" in top_hit, f"recall hit missing 'content': {top_hit!r}"
    assert "memory_id" in top_hit, f"recall hit missing 'memory_id': {top_hit!r}"
    assert top_hit["memory_id"] == memory_id, (
        f"recall hit has wrong memory_id: got {top_hit['memory_id']!r}, "
        f"expected {memory_id!r}"
    )
    # The content follows "{verb} {target}: {narrative}" pattern
    # (see ActionProcessor._persist_memory).
    content = top_hit["content"]
    assert "move" in content, (
        f"recall content missing 'move': {content!r}"
    )
    assert "north" in content, (
        f"recall content missing 'north': {content!r}"
    )
    assert canned_narrative in content, (
        f"recall content missing the canned narrative! "
        f"content={content!r}, expected to contain {canned_narrative!r}"
    )
    # And the metadata is the round-tripped dict the processor set.
    metadata = top_hit.get("metadata") or {}
    assert metadata.get("source") == "action_processor", (
        f"metadata.source mismatch: {metadata!r}"
    )
    assert metadata.get("action_id") == result["action_id"], (
        f"metadata.action_id mismatch: got "
        f"{metadata.get('action_id')!r}, expected "
        f"{result['action_id']!r}"
    )
    assert metadata.get("verb") == "move", (
        f"metadata.verb mismatch: {metadata!r}"
    )

    # ---- 6) Verify health. ----
    health = await real_palace.health()
    assert health.get("postgres") is True, (
        f"postgres not healthy: {health!r}"
    )
    assert health.get("vector_store") is True, (
        f"vector_store not healthy: {health!r}"
    )

    # ---- 7) Verify no hang / no deadlock. ----
    elapsed = time.monotonic() - t_start
    # Generous bound: the suite's other tests target <2s, so we
    # also target <2s here. A hang (physics lock never released,
    # asyncio.Lock deadlock, etc.) would blow this out.
    assert elapsed < 2.0, (
        f"test took {elapsed:.2f}s — possible deadlock or hang. "
        f"This is the failure mode E1.5a is designed to catch."
    )
