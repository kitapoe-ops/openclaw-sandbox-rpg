"""
Tests for Soul Transfer (Wave 2 Core #2).

Covers:
  - 3-dimensional payload (memories + character_state + prompt_context)
  - Degradation engine (random [0.6, 0.9])
  - Atomic SQLite persistence
  - Anti-predictability (different transfers = different factors)
  - Self-transfer rejection
  - Anti-suicide: degraded soul is NEVER identical to source
"""
from __future__ import annotations

import os
import sys
import asyncio
import random
from pathlib import Path

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
async def memory_palace(tmp_path):
    """Fresh MemoryPalace + soul DB for each test."""
    from backend.memory_palace import MemoryPalace
    db_path = tmp_path / "memory_test.db"
    palace = MemoryPalace(db_path=str(db_path))
    yield palace


@pytest_asyncio.fixture
async def soul_service(memory_palace, tmp_path):
    """SoulTransferService wrapping a fresh MemoryPalace."""
    from backend.soul_transfer import SoulTransferService
    soul_db = tmp_path / "soul_test.db"
    svc = SoulTransferService(
        memory_palace=memory_palace,
        soul_db_path=str(soul_db),
    )
    yield svc


# ============================================
# Test 1 \u2014 Constants and bounds
# ============================================


class TestConstants:
    def test_degradation_bounds(self):
        from backend.soul_transfer import DEGRADATION_MIN, DEGRADATION_MAX
        assert DEGRADATION_MIN == 0.6
        assert DEGRADATION_MAX == 0.9
        assert DEGRADATION_MIN < DEGRADATION_MAX


# ============================================
# Test 2 \u2014 PromptContext serialization
# ============================================


class TestPromptContext:
    def test_default_construction(self):
        from backend.soul_transfer import PromptContext
        ctx = PromptContext()
        assert ctx.recent_choices == []
        assert ctx.attitude_history == []
        assert ctx.npc_relationships == {}
        assert ctx.scene_recaps == []
        assert ctx.last_narrative == ""

    def test_to_from_dict_roundtrip(self):
        from backend.soul_transfer import PromptContext
        original = PromptContext(
            recent_choices=["chose to fight", "chose to flee"],
            attitude_history=[{"caution": "balanced"}],
            npc_relationships={"npc_merchant": "friendly"},
            scene_recaps=["entered tavern", "met merchant"],
            last_narrative="You see a merchant smiling.",
        )
        d = original.to_dict()
        restored = PromptContext.from_dict(d)
        assert restored.recent_choices == original.recent_choices
        assert restored.last_narrative == original.last_narrative

    def test_from_dict_with_empty_data(self):
        from backend.soul_transfer import PromptContext
        restored = PromptContext.from_dict({})
        assert restored.recent_choices == []


# ============================================
# Test 3 \u2014 Degradation Engine
# ============================================


class TestDegradation:
    def test_degrade_character_state_downshifts(self):
        from backend.soul_transfer import degrade_character_state
        rng = random.Random(42)
        state = {
            "physical": {
                "stamina_level": "fresh",
                "health_status": "healthy",
                "active_effects": ["a", "b", "c", "d", "e", "f", "g", "h"],
            },
            "mental": {"morale_level": "calm"},
            "inventory": {"items": [{"item_id": f"item_{i}"} for i in range(10)]},
            "relationships": {f"npc_{i}": "friendly" for i in range(6)},
        }
        degraded, audit = degrade_character_state(state, 0.7, rng)
        # Stamina downshifted
        assert degraded["physical"]["stamina_level"] == "slight_breath"
        # Healthy stays healthy (no downshift on full health)
        assert degraded["physical"]["health_status"] == "healthy"
        # Morale downshifted
        assert degraded["mental"]["morale_level"] == "neutral"
        # Active effects: 10-30% dropped (5-7 of 8 kept)
        assert 5 <= len(degraded["physical"]["active_effects"]) <= 8
        # Inventory: top 3
        assert len(degraded["inventory"]["items"]) == 3
        # Audit log present
        assert audit["factor_used"] == 0.7
        assert audit["stamina"]["new"] == "slight_breath"

    def test_degrade_prompt_context_drops_items(self):
        from backend.soul_transfer import PromptContext, degrade_prompt_context
        rng = random.Random(42)
        ctx = PromptContext(
            recent_choices=[f"choice_{i}" for i in range(20)],
            attitude_history=[{"caution": "balanced"} for _ in range(20)],
            scene_recaps=[f"scene_{i}" for i in range(20)],
            last_narrative="final scene",
        )
        degraded, audit = degrade_prompt_context(ctx, 0.7, rng)
        # 30-50% dropped from recent_choices \u2192 10-14 kept
        assert 10 <= len(degraded.recent_choices) <= 14
        # 40-60% dropped from attitude_history
        assert 8 <= len(degraded.attitude_history) <= 12
        # last_narrative preserved (single string)
        assert degraded.last_narrative == "final scene"

    def test_degrade_memories_lowers_salience(self):
        from backend.soul_transfer import degrade_memories
        rng = random.Random(42)
        memories = [
            {"id": f"m_{i}", "salience": 0.8, "metadata": {}}
            for i in range(10)
        ]
        degraded, audit = degrade_memories(memories, 0.7, rng)
        # All saliences multiplied by 0.7
        for m in degraded:
            assert 0.5 < m["salience"] < 0.6  # 0.8 * 0.7 = 0.56
            assert m["metadata"].get("soul_transferred") is True
        # 5-15% dropped (lowest salience)
        assert 8 <= len(degraded) <= 10

    def test_degradation_factor_out_of_range_raises(self):
        from backend.soul_transfer import (
            PromptContext,
            degrade_character_state,
            degrade_prompt_context,
            degrade_memories,
        )
        rng = random.Random()
        with pytest.raises(ValueError):
            degrade_character_state({}, 0.5, rng)  # below 0.6
        with pytest.raises(ValueError):
            degrade_character_state({}, 0.95, rng)  # above 0.9

    def test_clamp_helper(self):
        from backend.soul_transfer import _clamp
        assert _clamp(0.5, 0.0, 1.0) == 0.5
        assert _clamp(-0.1, 0.0, 1.0) == 0.0
        assert _clamp(1.5, 0.0, 1.0) == 1.0

    def test_downshift_semantic(self):
        from backend.soul_transfer import _downshift_semantic
        levels = ["a", "b", "c", "d"]
        assert _downshift_semantic("a", levels, 1) == "b"
        assert _downshift_semantic("a", levels, 5) == "d"  # clamp to last
        assert _downshift_semantic("zzz", levels, 1) == "zzz"  # not in list


# ============================================
# Test 4 \u2014 SoulTransferService
# ============================================


class TestSoulTransferService:
    @pytest.mark.asyncio
    async def test_self_transfer_rejected(self, soul_service):
        state = {"physical": {"stamina_level": "fresh"}}
        with pytest.raises(ValueError, match="must differ"):
            await soul_service.transfer(
                source_character_id="char_a",
                target_character_id="char_a",
                character_state=state,
            )

    @pytest.mark.asyncio
    async def test_assemble_payload_3_dimensions(self, soul_service, memory_palace):
        # Seed source memories
        await memory_palace.add_memory(
            "src", "met a wizard", "episodic", "scene", salience=0.9
        )
        await memory_palace.add_memory(
            "src", "the wizard is named Gandalf", "semantic", "scene", salience=0.85
        )
        state = {
            "physical": {"stamina_level": "fresh", "active_effects": []},
            "mental": {"morale_level": "calm"},
        }
        soul = await soul_service.assemble_payload(
            source_character_id="src",
            target_character_id="dst",
            character_state=state,
            degradation_factor=0.7,
        )
        # 3 dimensions populated
        assert len(soul.memories) == 2
        assert soul.character_state["physical"]["stamina_level"] == "slight_breath"
        assert soul.prompt_context.last_narrative == ""  # default
        # Audit metadata present
        assert soul.transfer_metadata["degradation_factor"] == 0.7
        assert "memory_audit" in soul.transfer_metadata
        assert "state_audit" in soul.transfer_metadata
        assert "context_audit" in soul.transfer_metadata

    @pytest.mark.asyncio
    async def test_persist_and_retrieve(self, soul_service, memory_palace):
        await memory_palace.add_memory("src", "x", "episodic", "scene")
        soul = await soul_service.assemble_payload(
            "src", "dst", {"physical": {"stamina_level": "fresh"}}
        )
        await soul_service.persist_soul(soul)
        # Retrieve
        retrieved = await soul_service.get_soul(soul.soul_id)
        assert retrieved is not None
        assert retrieved.soul_id == soul.soul_id
        assert retrieved.source_character_id == "src"
        assert retrieved.target_character_id == "dst"
        assert len(retrieved.memories) == 1

    @pytest.mark.asyncio
    async def test_get_soul_not_found(self, soul_service):
        result = await soul_service.get_soul("nonexistent_id_12345")
        assert result is None

    @pytest.mark.asyncio
    async def test_apply_soul_marks_applied(self, soul_service, memory_palace):
        await memory_palace.add_memory("src", "x", "episodic", "scene")
        soul = await soul_service.assemble_payload(
            "src", "dst", {"physical": {"stamina_level": "fresh"}}
        )
        await soul_service.persist_soul(soul)
        result = await soul_service.apply_soul(soul)
        assert result["rows_updated"] == 1
        # Should no longer appear in pending
        pending = await soul_service.get_pending_souls("dst")
        assert soul.soul_id not in [s.soul_id for s in pending]

    @pytest.mark.asyncio
    async def test_get_pending_souls(self, soul_service, memory_palace):
        await memory_palace.add_memory("src", "x", "episodic", "scene")
        soul1 = await soul_service.assemble_payload("src", "dst", {})
        soul2 = await soul_service.assemble_payload("src", "dst", {})
        await soul_service.persist_soul(soul1)
        await soul_service.persist_soul(soul2)
        pending = await soul_service.get_pending_souls("dst")
        assert len(pending) == 2

    @pytest.mark.asyncio
    async def test_count_transfers(self, soul_service, memory_palace):
        await memory_palace.add_memory("src", "x", "episodic", "scene")
        for _ in range(3):
            soul = await soul_service.assemble_payload("src", "dst", {})
            await soul_service.persist_soul(soul)
        n = await soul_service.count_transfers("src")
        assert n == 3
        n2 = await soul_service.count_transfers("dst")
        assert n2 == 3  # dst is also involved


# ============================================
# Test 5 \u2014 Anti-Predictability
# ============================================


class TestAntiPredictability:
    @pytest.mark.asyncio
    async def test_different_transfers_produce_different_factors(self, soul_service, memory_palace):
        """No two transfers should produce the same degradation (anti-pattern)."""
        factors = []
        for _ in range(10):
            soul = await soul_service.assemble_payload(
                "src", "dst", {"physical": {"stamina_level": "fresh"}},
            )
            factors.append(soul.degradation_factor)
        # Should have variation
        assert len(set(factors)) > 1  # at least 2 unique values
        # All within bounds
        for f in factors:
            assert 0.6 <= f <= 0.9

    @pytest.mark.asyncio
    async def test_deterministic_with_seed(self, memory_palace, tmp_path):
        """With same seed, the degradation should be deterministic (for testing)."""
        from backend.soul_transfer import SoulTransferService
        soul_db = tmp_path / "soul_deterministic.db"
        svc1 = SoulTransferService(
            memory_palace=memory_palace,
            soul_db_path=str(soul_db),
            rng_seed=42,
        )
        await memory_palace.add_memory("src", "x", "episodic", "scene")
        soul1 = await svc1.assemble_payload("src", "dst", {})
        # Second service with same seed
        svc2 = SoulTransferService(
            memory_palace=memory_palace,
            soul_db_path=str(soul_db),
            rng_seed=42,
        )
        soul2 = await svc2.assemble_payload("src", "dst", {})
        assert soul1.degradation_factor == soul2.degradation_factor


# ============================================
# Test 6 \u2014 Anti-Suicide
# ============================================


class TestAntiSuicide:
    @pytest.mark.asyncio
    async def test_soul_is_never_identical_to_source(self, soul_service, memory_palace):
        """
        Anti-suicide invariant: a soul can never be a perfect copy.
        Even with max-degradation-factor=0.9, memories get a 5-15% drop
        on top, so the soul is ALWAYS lossy.
        """
        # Seed source with 20 memories
        for i in range(20):
            await memory_palace.add_memory(
                "src", f"unique memory {i}", "episodic", "scene", salience=0.9
            )
        # Transfer with MAX factor (0.9)
        soul = await soul_service.assemble_payload(
            "src", "dst",
            {"physical": {"stamina_level": "fresh", "active_effects": []}},
            degradation_factor=0.9,
        )
        # 5-15% drop means at least 1 memory lost (out of 20)
        assert len(soul.memories) < 20
        # Stamina downshifted (no longer "fresh")
        assert soul.character_state["physical"]["stamina_level"] != "fresh"

    @pytest.mark.asyncio
    async def test_min_factor_still_degrades(self, soul_service, memory_palace):
        """Even factor=0.6 (worst case) still applies additional drops."""
        for i in range(20):
            await memory_palace.add_memory(
                "src", f"mem_{i}", "episodic", "scene", salience=0.9
            )
        soul = await soul_service.assemble_payload(
            "src", "dst", {"physical": {"stamina_level": "fresh"}},
            degradation_factor=0.6,
        )
        # All saliences multiplied by 0.6
        for m in soul.memories:
            assert m["salience"] < 0.6  # 0.9 * 0.6 = 0.54
        # 5-15% drop
        assert len(soul.memories) < 20


# ============================================
# Test 7 \u2014 Schema integrity
# ============================================


class TestSchema:
    def test_initialize_storage_idempotent(self, tmp_path):
        from backend.soul_transfer import SoulTransferService
        from backend.memory_palace import MemoryPalace
        palace = MemoryPalace(db_path=str(tmp_path / "mem.db"))
        soul_db = tmp_path / "soul.db"
        # Init twice
        SoulTransferService(memory_palace=palace, soul_db_path=str(soul_db))
        SoulTransferService(memory_palace=palace, soul_db_path=str(soul_db))
        # Verify table exists
        import sqlite3
        conn = sqlite3.connect(str(soul_db))
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='soul_payloads'"
            ).fetchall()
            assert len(rows) == 1
        finally:
            conn.close()
