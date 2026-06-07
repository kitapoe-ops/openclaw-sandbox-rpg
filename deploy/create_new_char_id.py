"""Create the 'new_character_id' placeholder character that the
SPA currently hardcodes. Once the SPA gains a real 'Create
Character' POST flow, this script can be deleted.

This is a hotfix for the L2-E production stack so existing
in-flight browser sessions don't get a 404 hang.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp")

from sqlalchemy import text
from backend.db import AsyncSessionLocal


async def main():
    cid = "new_character_id"
    name = "新冒險者"
    world_id = "dnd_5e_forgotten_realms_phandalin"
    scene_id = "loc_phandalin_town"
    profile = {
        "physical": {
            "health_status": "healthy",
            "stamina_level": "fresh",
            "active_effects": ["well_fed", "well_rested"],
        },
        "mental": {
            "morale_level": "calm",
            "alertness_level": "focused",
        },
        "attitude": {
            "honor": "honest",
            "caution": "bold",
            "empathy": "compassionate",
            "violence": "defensive",
            "curiosity": "curious",
        },
        "inventory": {
            "items": [
                {"item_id": "item_leather_armor", "quantity": 1},
                {"item_id": "item_iron_dagger", "quantity": 1},
                {"item_id": "item_dry_rations", "quantity": 3},
                {"item_id": "item_torch", "quantity": 2},
            ],
            "equipment": {
                "armor": "item_leather_armor",
                "weapon": "item_iron_dagger",
                "accessory_1": None,
                "accessory_2": None,
            },
        },
        "memories": [],
        "relationships": {},
    }

    async with AsyncSessionLocal() as s:
        # Check if already exists
        existing = await s.execute(
            text("SELECT 1 FROM character_states WHERE character_id = :cid"),
            {"cid": cid},
        )
        if existing.first():
            print(f"Character '{cid}' already exists; no-op.")
            return

        await s.execute(
            text(
                "INSERT INTO character_states "
                "(character_id, name, world_id, current_scene_id, "
                " semantic_profile, is_npc_mode, is_alive, created_at, updated_at) "
                "VALUES (:cid, :name, :wid, :sid, "
                "        CAST(:profile AS jsonb), false, true, now(), now())"
            ),
            {
                "cid": cid,
                "name": name,
                "wid": world_id,
                "sid": scene_id,
                "profile": __import__("json").dumps(profile, ensure_ascii=False),
            },
        )
        await s.commit()
        print(f"Created character '{cid}' (name='{name}') in scene '{scene_id}'.")


asyncio.run(main())
