"""Seed extra Phandalin scenes that the M3 LLM likes to generate.

The LLM has shown a tendency to return scene IDs like
'loc_phandalin_town_square' that don't exist in the DB. We
pre-seed a few common variants so the foreign-key UPDATE
in Q6 STEP 3 doesn't crash.

All scenes are real Phandalin locations from the published
D&D 5e Lost Mine of Phandelver module; the ID slugs match
the YAML in /workspace data so M3's output aligns with
canonical names.
"""
import asyncio
import sys

sys.path.insert(0, r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp")

from sqlalchemy import text
from backend.db import AsyncSessionLocal


SCENES = [
    {
        "id": "loc_phandalin_town_square",
        "name": "Phandalin Town Square",
        "world_id": "dnd_5e_forgotten_realms_phandalin",
        "description": "Phandalin town center, where wagon tracks converge. A stone fountain sits at the crossroads, and the wooden buildings crowd the edges of the square.",
        "location_tag": "town",
        "environment_tags": ["urban", "day", "outdoor"],
        "active_npcs": ["npc_sister_garaele", "npc_halia_thornton"],
        "atmosphere": "peaceful",
    },
    {
        "id": "loc_phandalin_stonecarver",
        "name": "Phandalin Stonecarver's Guild",
        "world_id": "dnd_5e_forgotten_realms_phandalin",
        "description": "A soot-stained stoneworker's shop. Crates of uncut stone line the walls. The guild master is rarely seen; her apprentice watches the front.",
        "location_tag": "town",
        "environment_tags": ["urban", "indoor", "shop"],
        "active_npcs": ["npc_stonecarver_apprentice"],
        "atmosphere": "neutral",
    },
    {
        "id": "loc_phandalin_tavern",
        "name": "Phandalin Stonehill Inn",
        "world_id": "dnd_5e_forgotten_realms_phandalin",
        "description": "A warm, two-story inn with low-beamed ceilings. The smell of bread and ale drifts from the common room. A buxom barmaid moves between tables.",
        "location_tag": "town",
        "environment_tags": ["urban", "indoor", "tavern"],
        "active_npcs": ["npc_innkeeper", "npc_barmaid"],
        "atmosphere": "warm",
    },
    {
        "id": "loc_phandalin_general_store",
        "name": "Phandalin General Store",
        "world_id": "dnd_5e_forgotten_realms_phandalin",
        "description": "A cluttered shop selling dry goods, basic weapons, and a few alchemical odds and ends. The proprietor is a thin man with spectacles.",
        "location_tag": "town",
        "environment_tags": ["urban", "indoor", "shop"],
        "active_npcs": ["npc_shopkeeper_linene"],
        "atmosphere": "neutral",
    },
    {
        "id": "loc_phandalin_barracks",
        "name": "Phandalin Old Barracks",
        "world_id": "dnd_5e_forgotten_realms_phandalin",
        "description": "An abandoned wooden building at the edge of town. Crumbling walls; an air of recent occupation. Redbrand thugs are commonly seen here.",
        "location_tag": "town",
        "environment_tags": ["urban", "indoor", "ruins"],
        "active_npcs": ["npc_redbrand_thug", "npc_redbrand_thug", "npc_redbrand_captain"],
        "atmosphere": "tense",
    },
    {
        "id": "loc_phandalin_temple",
        "name": "Phandalin Shrine of Luck",
        "world_id": "dnd_5e_forgotten_realms_phandalin",
        "description": "A small stone chapel. Sister Garaele tends the shrine, lighting candles for the goddess Tymora. The wooden pews are worn smooth.",
        "location_tag": "town",
        "environment_tags": ["urban", "indoor", "sacred"],
        "active_npcs": ["npc_sister_garaele"],
        "atmosphere": "peaceful",
    },
    {
        "id": "loc_phandalin_road_east",
        "name": "Phandalin East Road",
        "world_id": "dnd_5e_forgotten_realms_phandalin",
        "description": "The dirt road out of Phandalin heading east toward Neverwinter. Tall grass flanks the path. The wagon ruts are deep.",
        "location_tag": "road",
        "environment_tags": ["outdoor", "day", "wilderness"],
        "active_npcs": [],
        "atmosphere": "neutral",
    },
    {
        "id": "loc_phandalin_road_south",
        "name": "Phandalin South Road",
        "world_id": "dnd_5e_forgotten_realms_phandalin",
        "description": "The dirt road leading south out of Phandalin toward the High Road and beyond. A few travelers can be seen on the path.",
        "location_tag": "road",
        "environment_tags": ["outdoor", "day", "wilderness"],
        "active_npcs": [],
        "atmosphere": "neutral",
    },
    {
        "id": "loc_phandalin_tresendar",
        "name": "Tresendar Manor (ruin)",
        "world_id": "dnd_5e_forgotten_realms_phandalin",
        "description": "An old stone manor, abandoned for years. Goblin tracks lead to a half-collapsed entrance.",
        "location_tag": "wilderness",
        "environment_tags": ["outdoor", "ruins", "goblin_lair"],
        "active_npcs": ["npc_goblin", "npc_goblin", "npc_goblin_boss"],
        "atmosphere": "tense",
    },
]


async def main() -> None:
    import json as _json
    async with AsyncSessionLocal() as s:
        for sc in SCENES:
            existing = await s.execute(
                text("SELECT 1 FROM scenes WHERE id = :sid"), {"sid": sc["id"]}
            )
            if existing.first():
                print(f"  exists: {sc['id']}")
                continue
            await s.execute(
                text(
                    "INSERT INTO scenes "
                    "(id, world_id, name, description, location_tag, "
                    " environment_tags, active_npcs, atmosphere, is_dynamic, "
                    " created_at, updated_at) "
                    "VALUES (:id, :wid, :name, :desc, :lt, "
                    "        CAST(:env AS jsonb), CAST(:npcs AS jsonb), "
                    "        :atmo, false, now(), now())"
                ),
                {
                    "id": sc["id"],
                    "wid": sc["world_id"],
                    "name": sc["name"],
                    "desc": sc["description"],
                    "lt": sc["location_tag"],
                    "env": _json.dumps(sc["environment_tags"]),
                    "npcs": _json.dumps(sc["active_npcs"]),
                    "atmo": sc["atmosphere"],
                },
            )
            print(f"  inserted: {sc['id']}")
        await s.commit()
    print(f"\nTotal scenes now in DB: {len(SCENES) + 1}")


asyncio.run(main())
