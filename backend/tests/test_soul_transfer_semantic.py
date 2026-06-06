"""
Soul Transfer — Semantic Tests (Phase F2, 2026-06-05)
=====================================================

Replaces the legacy `test_soul_transfer.py` (deleted 2026-06-05).
The legacy tests were tied to numerical `degradation_factor` and
`degrade_*` helpers, which are removed in F2.

The new tests cover the 3 user-flagged critical decisions:

  Decision 1 (tier list + LLM fallback)
    * `test_tier_list_known_state_picks_tier_downgrade`
    * `test_tier_list_unknown_state_uses_llm_fallback`
    * `test_no_llm_returns_uncategorized_fallback`
    * `test_llm_invalid_output_uses_uncategorized_fallback`

  Decision 2 (anti-predictability)
    * `test_anti_predictability_two_consecutive_differ`
    * `test_anti_predictability_repeated_returns_varied_results`

  Decision 3 (anti-exploit rules)
    * `test_anti_exploit_same_scene_required`
    * `test_anti_exploit_vessel_not_occupied`
    * `test_anti_exploit_source_must_be_transferable`
    * `test_anti_exploit_self_target_rejected`

Plus:
  * `test_cross_character_memory_isolation` (rule 7)
  * `test_atomicity_persist_failure_no_partial_state` (V2)
  * `test_concurrent_apply_only_one_succeeds` (V3)

Total: 12 tests. Target: <2s.

Run with:
    .venv/Scripts/python.exe -m pytest backend/tests/test_soul_transfer_semantic.py -q
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from typing import Any, Dict, List, Optional

import pytest
import pytest_asyncio

_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ============================================
# Fixtures
# ============================================


@pytest_asyncio.fixture
async def engine(tmp_path):
    """A fresh SemanticSoulTransfer with in-memory storage."""
    from backend.soul_transfer import SemanticSoulTransfer
    return SemanticSoulTransfer(soul_db_path=":memory:")


@pytest_asyncio.fixture
async def engine_with_mock_llm(tmp_path):
    """SemanticSoulTransfer with a mock LLM that returns a known tag."""
    from backend.llm_client import MockLLMClient
    from backend.soul_transfer import SemanticSoulTransfer
    mock = MockLLMClient(
        canned_response='{"degraded_state": "測試降級"}',
    )
    return SemanticSoulTransfer(
        soul_db_path=":memory:",
        llm_client=mock,
    )


@pytest_asyncio.fixture
async def engine_with_bad_llm(tmp_path):
    """SemanticSoulTransfer with a mock LLM that returns garbage."""
    from backend.llm_client import MockLLMClient
    from backend.soul_transfer import SemanticSoulTransfer
    mock = MockLLMClient(canned_response='{"degraded_state": "!!garbage!!"}')
    return SemanticSoulTransfer(
        soul_db_path=":memory:",
        llm_client=mock,
    )


@pytest_asyncio.fixture
async def engine_with_isolation_guard():
    """SemanticSoulTransfer with a fake MemoryIsolationGuard."""
    from backend.soul_transfer import SemanticSoulTransfer

    class FakeGuard:
        def __init__(self, allow: bool = True) -> None:
            self.allow = allow
            self.calls: int = 0

        def require(self, requester_id, scene_id, target_character_id, op="read"):
            self.calls += 1
            if not self.allow:
                from backend.memory_isolation import MemoryIsolationError
                raise MemoryIsolationError("denied by fake guard")

    guard = FakeGuard(allow=True)
    engine = SemanticSoulTransfer(soul_db_path=":memory:", memory_isolation_guard=guard)
    return engine, guard


# ============================================
# Decision 1 — Tier List vs LLM-driven downgrade
# ============================================


class TestTierList:
    @pytest.mark.asyncio
    async def test_tier_list_known_state_picks_tier_downgrade(self, engine):
        """
        Decision 1 (Option A): for a known source state, the engine
        should pick from the tier list and NOT call the LLM (no llm
        client is wired here).
        """
        result = await engine.compute_degradation(
            source_state=["右手骨折"],
            vessel_id="vessel_alpha",
        )
        assert result["downgrade_method"] == "tier_list"
        assert result["downgraded_from"] == "右手骨折"
        # Pick is from the tier list for "右手骨折"
        from backend.soul_transfer import TIER_DOWNGRADES
        valid_picks = TIER_DOWNGRADES["右手骨折"]
        assert result["downgraded_to"] in valid_picks
        # The new tag set is the old set minus the source tag, plus
        # the new pick.
        assert "右手骨折" not in result["new_tags"]
        assert result["downgraded_to"] in result["new_tags"]

    @pytest.mark.asyncio
    async def test_tier_list_unknown_state_uses_llm_fallback(
        self, engine_with_mock_llm,
    ):
        """
        Decision 1 (Option B): for a state NOT in the tier list, the
        engine should call the LLM and use the LLM's answer.
        """
        engine = engine_with_mock_llm
        result = await engine.compute_degradation(
            source_state=["一種從未見過的異常狀態"],
            vessel_id="vessel_alpha",
        )
        assert result["downgrade_method"] == "llm_fallback"
        assert result["downgraded_from"] == "一種從未見過的異常狀態"
        # The mock returns "測試降級" — a valid CJK tag
        assert result["downgraded_to"] == "測試降級"
        # LLM was called exactly once
        assert engine.llm_client.calls == 1

    @pytest.mark.asyncio
    async def test_no_llm_returns_uncategorized_fallback(self, engine):
        """
        Decision 1: if no LLM is wired, an unknown state falls back
        to "未分類" (uncategorized) so the transfer is never blocked.
        """
        result = await engine.compute_degradation(
            source_state=["一種從未見過的異常狀態"],
            vessel_id="vessel_alpha",
        )
        assert result["downgrade_method"] == "llm_fallback"
        assert result["downgraded_to"] == "未分類"

    @pytest.mark.asyncio
    async def test_llm_invalid_output_uses_uncategorized_fallback(
        self, engine_with_bad_llm,
    ):
        """
        Decision 1 + F1 D2 alignment: the LLM output is validated
        against the F1 tag rules. If invalid, we fall back to
        "未分類" (never raise, never block the transfer).
        """
        result = await engine_with_bad_llm.compute_degradation(
            source_state=["另一個未知狀態"],
            vessel_id="vessel_beta",
        )
        # The LLM returned "!!garbage!!" which fails the CJK regex.
        # The engine should reject it and use "未分類".
        assert result["downgrade_method"] == "llm_fallback"
        assert result["downgraded_to"] == "未分類"


# ============================================
# Decision 2 — Anti-predictability
# ============================================


class TestAntiPredictability:
    @pytest.mark.asyncio
    async def test_anti_predictability_two_consecutive_differ(self, engine):
        """
        Decision 2: if the user transfers 3 times in a row to the
        SAME vessel, the result should not be predictable. We assert
        that two consecutive calls produce different `downgraded_to`
        values when the tier list has ≥ 2 entries.
        """
        results = []
        for _ in range(2):
            r = await engine.compute_degradation(
                source_state=["非常健康"],
                vessel_id="vessel_alpha",
            )
            results.append(r["downgraded_to"])
        # Anti-predictability: at least one of the two differs
        # (the second MUST differ from the first if the tier list
        # has ≥ 2 entries).
        from backend.soul_transfer import TIER_DOWNGRADES
        tier_choices = TIER_DOWNGRADES["非常健康"]
        assert len(tier_choices) >= 2
        assert results[0] in tier_choices
        assert results[1] in tier_choices
        # The second is NOT equal to the first
        assert results[1] != results[0], (
            f"anti-predictability violated: two consecutive transfers "
            f"both produced {results[0]!r}"
        )

    @pytest.mark.asyncio
    async def test_anti_predictability_repeated_returns_varied_results(
        self, engine,
    ):
        """
        Decision 2: across N=10 transfers, the distribution of
        `downgraded_to` should hit at least 2 distinct values
        (with overwhelming probability for a 4-entry tier list).
        """
        from backend.soul_transfer import TIER_DOWNGRADES
        tier_choices = TIER_DOWNGRADES["健康"]  # 3 entries
        results = set()
        for i in range(10):
            r = await engine.compute_degradation(
                source_state=["健康"],
                vessel_id=f"vessel_{i}",  # different vessel per call
            )
            results.add(r["downgraded_to"])
        # All picks are from the tier list
        for pick in results:
            assert pick in tier_choices
        # And we got at least 2 distinct values
        assert len(results) >= 2


# ============================================
# Decision 3 — Anti-Exploit Rules
# ============================================


class TestAntiExploit:
    def test_anti_exploit_same_scene_required(self, engine):
        """
        Decision 3 (rule 1): soul can only transfer to a vessel in
        the same scene. The engine requires `scene_id` to be set.
        """
        from backend.soul_transfer import ANTI_EXPLOIT_RULE_1
        check = engine.is_transfer_allowed(
            source_character_id="char_a",
            source_state=["健康"],
            target_vessel_id="vessel_b",
            target_vessel_state=[],
            scene_id="",  # missing
        )
        assert check["allowed"] is False
        assert check["rule"] == ANTI_EXPLOIT_RULE_1

    def test_anti_exploit_vessel_not_occupied(self, engine):
        """
        Decision 3 (rule 2): a vessel with an active soul cannot
        receive a new soul. The engine inspects `target_vessel_state`
        and rejects if it has any non-empty tags.
        """
        check = engine.is_transfer_allowed(
            source_character_id="char_a",
            source_state=["健康"],
            target_vessel_id="vessel_b",
            target_vessel_state=["喜悅", "健康"],  # occupied
            scene_id="scene_1",
        )
        assert check["allowed"] is False
        assert "active soul" in check["reason"]

    def test_anti_exploit_source_must_be_transferable(self, engine):
        """
        Decision 3 (rule 5): source must be in a transferable state.
        A character in `完好無損` (perfectly intact) or `固著` (anchored)
        cannot have its soul transferred.
        """
        # Test 完好無損
        check = engine.is_transfer_allowed(
            source_character_id="char_a",
            source_state=["完好無損"],
            target_vessel_id="vessel_b",
            target_vessel_state=[],
            scene_id="scene_1",
        )
        assert check["allowed"] is False
        assert "non-transferable" in check["reason"]

        # Test 死亡
        check = engine.is_transfer_allowed(
            source_character_id="char_a",
            source_state=["死亡"],
            target_vessel_id="vessel_b",
            target_vessel_state=[],
            scene_id="scene_1",
        )
        assert check["allowed"] is False
        assert "lost" in check["reason"] or "non-transferable" in check["reason"]

    def test_anti_exploit_self_target_rejected(self, engine):
        """
        Decision 3 (anti-self-target): a soul cannot transfer to
        itself. The engine rejects when source == target.
        """
        check = engine.is_transfer_allowed(
            source_character_id="char_a",
            source_state=["健康"],
            target_vessel_id="char_a",  # self
            target_vessel_state=[],
            scene_id="scene_1",
        )
        assert check["allowed"] is False
        assert "self-transfer" in check["reason"]


# ============================================
# Cross-character memory isolation (rule 7)
# ============================================


class TestMemoryIsolation:
    @pytest.mark.asyncio
    async def test_cross_character_memory_isolation(self, engine_with_isolation_guard):
        """
        Decision 3 (rule 7): the memory_isolation_guard authorizes
        every cross-character memory access. If the guard denies,
        the transfer is blocked.
        """
        engine, guard = engine_with_isolation_guard
        # Happy path: guard allows → transfer succeeds
        record = await engine.execute_transfer(
            source_character_id="char_a",
            source_state=["健康"],
            target_vessel_id="vessel_b",
            target_vessel_state=[],
            scene_id="scene_1",
            carried_memories=["memory 1", "memory 2"],
            requester_id="player_1",
        )
        assert record.audit["anti_exploit_check"]["allowed"] is True
        # Guard was called once (for the source character's read access)
        assert guard.calls == 1

        # Sad path: guard denies → transfer blocked
        from backend.soul_transfer import SoulTransferNotAllowedError
        guard.allow = False
        with pytest.raises(SoulTransferNotAllowedError) as excinfo:
            await engine.execute_transfer(
                source_character_id="char_a",
                source_state=["健康"],
                target_vessel_id="vessel_b",
                target_vessel_state=[],
                scene_id="scene_1",
                carried_memories=["memory 3"],
                requester_id="player_1",
            )
        assert "memory isolation" in str(excinfo.value).lower()


# ============================================
# Atomicity (V2 — crash mid-transfer)
# ============================================


class TestAtomicity:
    @pytest.mark.asyncio
    async def test_atomicity_persist_failure_no_partial_state(
        self, engine, monkeypatch,
    ):
        """
        V2: force the SQLite commit() to fail. The transfer must
        roll back, leaving no partial soul_transfers row.
        """
        # First, do a successful transfer to confirm baseline
        record_ok = await engine.execute_transfer(
            source_character_id="char_a",
            source_state=["健康"],
            target_vessel_id="vessel_b",
            target_vessel_state=[],
            scene_id="scene_1",
        )
        assert await engine.count_transfers("vessel_b") == 1

        # Now patch _persist to raise
        def boom(record):
            raise RuntimeError("simulated commit failure")
        monkeypatch.setattr(engine, "_persist", boom)

        from backend.soul_transfer import SoulTransferError
        with pytest.raises(RuntimeError, match="simulated commit failure"):
            await engine.execute_transfer(
                source_character_id="char_a",
                source_state=["健康"],
                target_vessel_id="vessel_c",
                target_vessel_state=[],
                scene_id="scene_1",
            )
        # The first (successful) transfer is still there; the failed
        # one left no trace.
        assert await engine.count_transfers("vessel_c") == 0
        assert await engine.count_transfers("vessel_b") == 1


# ============================================
# Apply idempotency (V3 — concurrent apply)
# ============================================


class TestApplyIdempotency:
    @pytest.mark.asyncio
    async def test_concurrent_apply_only_one_succeeds(self, engine):
        """
        V3: two callers race to apply the same transfer record.
        The UPDATE...WHERE applied=0 clause must ensure only one
        updates the row; the other sees rows_updated=0.
        """
        record = await engine.execute_transfer(
            source_character_id="char_a",
            source_state=["健康"],
            target_vessel_id="vessel_b",
            target_vessel_state=[],
            scene_id="scene_1",
        )
        # Two concurrent apply_transfer calls on same record
        results = await asyncio.gather(
            engine.apply_transfer(record),
            engine.apply_transfer(record),
        )
        # Exactly one should have rows_updated=1, the other 0
        row_updates = [r["rows_updated"] for r in results]
        assert sorted(row_updates) == [0, 1], (
            f"Expected [0, 1] from concurrent apply, got {row_updates}"
        )
        # Verify final state: applied=1
        retrieved = await engine.get_transfer(record.transfer_id)
        assert retrieved.applied is True


# ============================================
# End-to-end: full transfer with all paths
# ============================================


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_full_transfer_flow(self, engine):
        """
        Integration smoke: build a transfer with carried memories,
        persist, retrieve, then apply.
        """
        record = await engine.execute_transfer(
            source_character_id="char_a",
            source_state=["右手骨折", "恐懼"],
            target_vessel_id="vessel_b",
            target_vessel_state=[],
            scene_id="scene_1",
            carried_memories=["met a wizard", "the wizard betrayed us"],
        )
        # Record has the new tags (one downgraded)
        assert "右手骨折" not in record.new_tags  # the downgraded one is gone
        assert "恐懼" in record.new_tags  # not in tier list, kept as-is
        # downgraded_to is from the tier list for "右手骨折"
        from backend.soul_transfer import TIER_DOWNGRADES
        assert record.downgraded_to in TIER_DOWNGRADES["右手骨折"]
        # Memories carried
        assert len(record.carried_memories) == 2
        # Retrieve by ID
        retrieved = await engine.get_transfer(record.transfer_id)
        assert retrieved is not None
        assert retrieved.transfer_id == record.transfer_id
        assert retrieved.new_tags == record.new_tags
        # Apply
        result = await engine.apply_transfer(record)
        assert result["rows_updated"] == 1
        # Now it's no longer pending
        pending = await engine.get_pending_transfers("vessel_b")
        assert record.transfer_id not in [p.transfer_id for p in pending]
