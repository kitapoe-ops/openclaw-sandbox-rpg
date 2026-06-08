import os
import sys
from pathlib import Path

# Ensure backend on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)))

import pytest
from backend.world_lore_db import WorldLoreDB
from backend.world_lore_loader import world_lore_loader


def test_expanded_world_file_structure():
    """Verify that the expanded world file exists and contains valid JSON."""
    json_path = Path(__file__).resolve().parent.parent.parent / "worlds" / "dnd_5e_forgotten_realms.json"
    assert json_path.exists(), "Expanded world JSON file does not exist."
    
    import json
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
        
    assert "world_meta" in data, "world_meta is missing in JSON."
    assert "npcs" in data, "npcs section is missing in JSON."
    assert "locations" in data, "locations section is missing in JSON."
    assert "items" in data, "items section is missing in JSON."
    assert "quests" in data, "quests section is missing in JSON."
    assert "starting_story" in data, "starting_story is missing in JSON."


@pytest.mark.asyncio
async def test_expanded_world_db_loading():
    """Verify that WorldLoreDB loads all expanded items, locations, npcs, and quests correctly."""
    json_path = Path(__file__).resolve().parent.parent.parent / "worlds" / "dnd_5e_forgotten_realms.json"
    
    db = WorldLoreDB(world_id="dnd_5e_forgotten_realms")
    success = db.load_from_json(json_path)
    assert success, "WorldLoreDB failed to load the JSON file."
    
    # Assert quantities of generated objects to ensure they match our scale expectations
    assert len(db.locations) >= 15, f"Expected at least 15 locations, got {len(db.locations)}"
    assert len(db.npcs) >= 75, f"Expected at least 75 npcs, got {len(db.npcs)}"
    assert len(db.items) >= 25, f"Expected at least 25 items, got {len(db.items)}"
    assert len(db.quests) >= 5, f"Expected at least 5 quests, got {len(db.quests)}"
    
    # Verify starting story is populated
    assert db.starting_story.get("title") == "凡達林礦坑的危機 (The Phandalin Crisis)"
    assert len(db.starting_story.get("prologue", "")) > 100
