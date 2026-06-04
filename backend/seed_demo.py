"""
Seed the in-memory store with demo data for the HTTP smoke test.

Usage:
    .\\.venv\\Scripts\\python.exe backend/seed_demo.py

This script:
1. Loads `worlds/dnd_5e_forgotten_realms.yaml` into `store.worlds["dnd_5e_forgotten_realms"]`.
2. Creates a single starter character (the half-elf ranger "雅莉亞・月羽" /
   `char_starter_aria`) — this is the YAML-defined D&D 5e half-elf ranger starter.
3. Prints `character_id` and `world_id` to stdout for use in the smoke test.

The script is idempotent: re-running replaces the existing character / world.

Exits 0 on success, non-zero on failure.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Force UTF-8 stdout on Windows so Traditional Chinese / Japanese kana print
# cleanly when this script is run from a non-UTF-8 console.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

# Make `from backend.store import store` work whether the script is run as
# `python backend/seed_demo.py` (cwd=project root) or as a module.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.store import store  # noqa: E402

WORLD_ID = "dnd_5e_forgotten_realms"
WORLD_YAML = PROJECT_ROOT / "worlds" / f"{WORLD_ID}.yaml"

# Map of starter character id -> (yaml id, normalized morale)
STARTER_CHAR_ID = "char_starter_aria"
STARTER_YAML_ID = "char_starter_aria"

# Morale normalization: the YAML uses "steady" / "high" / "neutral" — we map them
# onto the API enum {"elated", "calm", "neutral", "anxious", "despair"}.
MORALE_MAP = {
    "steady": "calm",
    "high": "elated",
    "low": "anxious",
    "neutral": "neutral",
}


def _now_iso() -> str:
    # Use timezone-aware UTC to avoid the deprecation warning on Python 3.12+
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_world() -> dict:
    """Load the D&D 5e Forgotten Realms YAML into the in-memory world store."""
    if not WORLD_YAML.exists():
        raise FileNotFoundError(f"World YAML not found: {WORLD_YAML}")

    with open(WORLD_YAML, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Wrap under world_meta so the rest of the system can read it consistently
    world_data = {
        "world_id": WORLD_ID,
        "loaded_at": _now_iso(),
        "config": cfg,
    }
    store.load_world(WORLD_ID, world_data)
    return world_data


def find_starter(cfg: dict, starter_yaml_id: str) -> dict:
    """Find a starter character in the YAML by id."""
    for sc in cfg.get("starter_characters", []):
        if sc.get("id") == starter_yaml_id:
            return sc
    raise KeyError(
        f"Starter character '{starter_yaml_id}' not found in {WORLD_YAML.name}"
    )


def build_character(starter: dict) -> dict:
    """Convert a YAML starter-character entry to the API character schema."""
    physical = dict(starter.get("physical", {}))
    mental = dict(starter.get("mental", {}))

    # Normalize morale to the API enum
    raw_morale = mental.get("morale_level", "neutral")
    mental["morale_level"] = MORALE_MAP.get(raw_morale, "neutral")

    # Ensure required fields exist
    physical.setdefault("stamina_level", "fresh")
    physical.setdefault("health_status", "healthy")
    physical.setdefault("active_effects", [])

    # Translate inventory_items -> inventory.items
    inventory = {
        "items": [
            {"item_id": iid, "quantity": 1}
            for iid in starter.get("inventory_items", [])
        ]
    }

    # Translate attitude (int values) -> attitude (string level names)
    # The API uses {"caution": "balanced"} style dicts. Map ints 0-3 to strings.
    def _int_to_level(v: int) -> str:
        if v <= 0:
            return "low"
        if v == 1:
            return "balanced"
        if v == 2:
            return "high"
        return "extreme"

    attitude = {
        k: _int_to_level(int(v)) for k, v in (starter.get("attitude") or {}).items()
    }

    now = _now_iso()
    return {
        "character_id": STARTER_CHAR_ID,
        "name": starter.get("name", "Unknown Hero"),
        "world_id": WORLD_ID,
        "race": starter.get("race"),
        "class": starter.get("class"),
        "background": starter.get("background"),
        "description": starter.get("description"),
        "physical": physical,
        "mental": mental,
        "attitude": attitude,
        "inventory": inventory,
        "current_location": starter.get("starting_location", ""),
        "memories": [],
        "created_at": now,
        "updated_at": now,
    }


def seed_all(verbose: bool = True) -> dict:
    """
    Run the full seed: load the world, create the starter character.

    Returns a dict with keys:
        - world_id: id of the loaded world
        - character_id: id of the created character
        - character_name: name of the created character
        - world_summary: {npcs, items, locations, quests, starter_characters} counts

    When `verbose` is True, also prints the standard [seed_demo] log lines and
    the parseable `CHARACTER_ID=...` / `WORLD_ID=...` summary block, so this
    function is safe to call from a CLI runner that wants to show progress.
    When False, runs silently — useful when the seed is invoked from inside
    the FastAPI process (e.g. via a launcher that calls `seed_all()` and
    then `uvicorn.run(...)` in the same Python process so the in-memory
    `store` singleton is shared between them).
    """
    def _v(msg: str) -> None:
        if verbose:
            print(msg)

    _v("[seed_demo] Loading world YAML...")
    world_data = load_world()
    cfg = world_data["config"]
    world_summary = {
        "npcs": len(cfg.get("npcs", [])),
        "items": len(cfg.get("items", [])),
        "locations": len(cfg.get("locations", [])),
        "quests": len(cfg.get("quests", [])),
        "starter_characters": len(cfg.get("starter_characters", [])),
    }
    _v(
        f"[seed_demo] World '{WORLD_ID}' loaded: "
        f"{world_summary['npcs']} NPCs, "
        f"{world_summary['items']} items, "
        f"{world_summary['locations']} locations, "
        f"{world_summary['quests']} quests, "
        f"{world_summary['starter_characters']} starter characters."
    )

    _v(f"[seed_demo] Looking up starter '{STARTER_YAML_ID}'...")
    starter = find_starter(cfg, STARTER_YAML_ID)
    character = build_character(starter)
    store.save_character(character)
    _v(
        f"[seed_demo] Character '{character['name']}' saved with "
        f"id='{character['character_id']}' "
        f"at location='{character['current_location']}'."
    )

    if verbose:
        # Final summary for downstream scripts (parseable)
        print("=" * 60)
        print(f"CHARACTER_ID={character['character_id']}")
        print(f"WORLD_ID={WORLD_ID}")
        print(f"CHARACTER_NAME={character['name']}")
        print("=" * 60)
        print("[seed_demo] OK")

    return {
        "world_id": WORLD_ID,
        "character_id": character["character_id"],
        "character_name": character["name"],
        "world_summary": world_summary,
    }


def main() -> int:
    try:
        seed_all(verbose=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[seed_demo] FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
