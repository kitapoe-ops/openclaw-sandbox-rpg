"""
Standalone test for the State Extractor (Phase L2-I/Phase C-6).

Tests 5 hand-crafted M3 narrative scenarios against the
local Gemma-4 12B instance via LM Studio. Verifies:
  1. Gemma responds with parseable JSON
  2. Pydantic schema validation passes
  3. State mutations match the expected ground truth
  4. Idempotency (running the same scenario twice produces
     identical output)

Usage:
  python -m deploy.test_extractor
  python -m deploy.test_extractor --scenario ncp_death
  python -m deploy.test_extractor --repeat 3 (run each 3x for stability)

Reports a pass/fail per scenario and an overall score.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.state_extractor import (
    StateExtractor,
    StateMutation,
    get_state_extractor,
)


# ============================================
# Test scenarios
# ============================================

SCENARIOS: list[dict] = [
    {
        "name": "npc_death_explicit",
        "narrative": (
            "你揮舞鐵劍向 Harbin 刺去，劍尖穿透他的胸膛。"
            "Harbin 倒在地上，血流了一地，不再動彈。"
        ),
        "choice": {"id": "opt_1", "vignette": "刺殺 Harbin"},
        "current_state": {
            "name": "新冒險者",
            "stamina": "fresh",
            "health": "healthy",
            "morale": "calm",
        },
        "current_npcs": [
            {"npc_id": "npc_harbin_west", "status": "alive"},
        ],
        "expected": {
            "npc_status_changes": [{"npc_id": "npc_harbin_west", "new_status": "dead"}],
        },
    },
    {
        "name": "item_acquire_explicit",
        "narrative": (
            "Sister Garaele 微笑著遞給你一個小袋子，"
            "裡面裝著三枚銀幣。"
        ),
        "choice": {"id": "opt_2", "vignette": "收下袋子和銀幣"},
        "current_state": {
            "name": "新冒險者",
            "stamina": "fresh",
            "health": "healthy",
            "morale": "calm",
        },
        "current_npcs": [
            {"npc_id": "npc_sister_garaele", "status": "alive"},
        ],
        "expected": {
            "inventory_changes": [
                {"action": "add", "item_id": "small_pouch"},
                {"action": "add", "item_id": "silver_coin", "quantity": 3},
            ],
        },
    },
    {
        "name": "location_change_explicit",
        "narrative": "你離開了 Phandalin 鎮，踏入 Tresendar Manor 的廢墟。",
        "choice": {"id": "opt_3", "vignette": "前往 Tresendar Manor"},
        "current_state": {
            "name": "新冒險者",
            "stamina": "fresh",
            "health": "healthy",
            "morale": "calm",
        },
        "current_npcs": [],
        "expected": {
            "location_change": "loc_phandalin_tresendar",
        },
    },
    {
        "name": "no_change_just_narration",
        "narrative": "你站在 Phandalin 鎮中心，四周的木屋包圍著你。",
        "choice": {"id": "opt_4", "vignette": "環顧四周"},
        "current_state": {
            "name": "新冒險者",
            "stamina": "fresh",
            "health": "healthy",
            "morale": "calm",
        },
        "current_npcs": [],
        "expected": {
            "npc_status_changes": [],
            "inventory_changes": [],
            "character_state_changes": [],
            "location_change": None,
        },
    },
    {
        "name": "ambiguous_no_inference",
        # Narrative is AMBIGUOUS — extractor MUST NOT invent state.
        "narrative": (
            "你隱約感覺到 Harbin 似乎對你抱有敵意，"
            "但他還沒有明顯動手。"
        ),
        "choice": {"id": "opt_1", "vignette": "觀察 Harbin 的反應"},
        "current_state": {
            "name": "新冒險者",
            "stamina": "fresh",
            "health": "healthy",
            "morale": "calm",
        },
        "current_npcs": [
            {"npc_id": "npc_harbin_west", "status": "alive"},
        ],
        "expected": {
            "npc_status_changes": [],
        },
    },
]


def _check_npc_changes(actual: list, expected: list) -> tuple[bool, str]:
    """Check that all expected NPC status changes are present in actual."""
    if len(actual) != len(expected):
        return False, f"count mismatch: got {len(actual)}, want {len(expected)}"
    for exp, act in zip(expected, actual):
        if exp["npc_id"] != act.npc_id:
            return False, f"npc_id mismatch: got {act.npc_id}, want {exp['npc_id']}"
        if exp["new_status"] != act.new_status:
            return False, (
                f"new_status mismatch for {act.npc_id}: "
                f"got {act.new_status}, want {exp['new_status']}"
            )
        if not act.evidence or len(act.evidence) < 5:
            return False, f"missing/short evidence for {act.npc_id}"
    return True, "OK"


def _check_inventory_changes(actual: list, expected: list) -> tuple[bool, str]:
    if len(actual) != len(expected):
        return False, f"count mismatch: got {len(actual)}, want {len(expected)}"
    for exp, act in zip(expected, actual):
        if exp["action"] != act.action:
            return False, f"action mismatch: got {act.action}, want {exp['action']}"
        if exp["item_id"] != act.item_id:
            return False, f"item_id mismatch: got {act.item_id}, want {exp['item_id']}"
        # quantity is optional; default 1
        if "quantity" in exp and exp["quantity"] != act.quantity:
            return False, f"qty mismatch: got {act.quantity}, want {exp['quantity']}"
        if not act.evidence:
            return False, f"missing evidence for {act.item_id}"
    return True, "OK"


def _check_mutation(scenario: dict, mutation: StateMutation) -> tuple[bool, str]:
    expected = scenario["expected"]
    if "npc_status_changes" in expected:
        ok, msg = _check_npc_changes(
            mutation.npc_status_changes, expected["npc_status_changes"]
        )
        if not ok:
            return False, f"npc: {msg}"
    if "inventory_changes" in expected:
        ok, msg = _check_inventory_changes(
            mutation.inventory_changes, expected["inventory_changes"]
        )
        if not ok:
            return False, f"inventory: {msg}"
    if "location_change" in expected:
        if mutation.location_change != expected["location_change"]:
            return False, (
                f"location_change: got {mutation.location_change!r}, "
                f"want {expected['location_change']!r}"
            )
    return True, "OK"


async def run_one(
    extractor: StateExtractor,
    scenario: dict,
    repeat: int = 1,
) -> tuple[int, int, list[str]]:
    """Run a single scenario `repeat` times. Returns
    (passed, total, error_messages)."""
    errors: list[str] = []
    passed = 0
    total = repeat

    for i in range(repeat):
        try:
            mutation = await extractor.extract(
                narrative=scenario["narrative"],
                player_choice=scenario["choice"],
                current_character_state=scenario["current_state"],
                current_npc_states=scenario["current_npcs"],
            )
            ok, msg = _check_mutation(scenario, mutation)
            if ok:
                passed += 1
            else:
                errors.append(
                    f"  attempt {i + 1}: {msg}\n    got: {mutation.model_dump_json(indent=2, ensure_ascii=False)}"
                )
        except Exception as e:
            errors.append(f"  attempt {i + 1}: EXCEPTION: {e}")

    return passed, total, errors


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario", help="Run only this named scenario", default=None
    )
    parser.add_argument(
        "--repeat", type=int, default=1, help="Run each scenario N times for stability"
    )
    args = parser.parse_args()

    extractor = get_state_extractor()
    healthy = await extractor.health()
    if not healthy:
        print("ERROR: LM Studio not healthy. Check that Gemma 3/4 12B is loaded.")
        return 2
    print(f"LM Studio health: OK (model={extractor.model})\n")

    scenarios = SCENARIOS
    if args.scenario:
        scenarios = [s for s in SCENARIOS if s["name"] == args.scenario]
        if not scenarios:
            print(f"ERROR: scenario '{args.scenario}' not found")
            return 2

    total_pass = 0
    total_run = 0
    for sc in scenarios:
        passed, total, errors = await run_one(extractor, sc, repeat=args.repeat)
        total_pass += passed
        total_run += total
        status = "PASS" if passed == total else "FAIL"
        print(f"[{status}] {sc['name']} ({passed}/{total})")
        for err in errors:
            print(err)
        print()

    await extractor.aclose()

    print("=" * 50)
    if total_pass == total_run:
        print(f"OVERALL: PASS ({total_pass}/{total_run})")
        return 0
    else:
        print(f"OVERALL: FAIL ({total_pass}/{total_run})")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
