"""
Unit tests for the world API endpoints.

Covers:
- GET   /api/world/{world_id}/state           world meta + counts
- GET   /api/world/{world_id}/parameters      param list with current levels
- POST  /api/world/{world_id}/etl             ETL trigger (placeholder)
- GET   /api/world/{world_id}                 full config
"""
import re
import pytest
import yaml as _yaml
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.store import store
from backend.api.world import router as world_router


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DND_WORLD_ID = "dnd_5e_forgotten_realms"
REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/tests → repo root
DND_YAML = REPO_ROOT / "worlds" / f"{DND_WORLD_ID}.yaml"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_store():
    """Wipe the global in-memory store before each test."""
    store.characters.clear()
    store.scenes.clear()
    store.worlds.clear()
    yield
    store.characters.clear()
    store.scenes.clear()
    store.worlds.clear()


@pytest.fixture
def client():
    """FastAPI TestClient with the world router mounted at /api/world."""
    app = FastAPI()
    app.include_router(world_router, prefix="/api/world", tags=["world"])
    return TestClient(app)


@pytest.fixture(scope="module")
def dnd_yaml_data():
    """Ground-truth counts loaded directly from the YAML, for cross-checks."""
    with open(DND_YAML, "r", encoding="utf-8") as f:
        return _yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestLoadDndWorld:
    def test_load_dnd_world(self, client):
        """GET /api/world/dnd_5e_forgotten_realms/state loads the YAML on demand."""
        resp = client.get(f"/api/world/{DND_WORLD_ID}/state")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # Required top-level keys
        assert body["world_id"] == DND_WORLD_ID
        assert body["loaded"] is True

        # world_meta should carry the meta block from the YAML
        meta = body["world_meta"]
        assert isinstance(meta, dict)
        assert "name" in meta and meta["name"]  # not empty

        # parameters should be a list with at least one entry
        assert isinstance(body["parameters"], list)
        assert len(body["parameters"]) >= 1
        # And they should be world_parameter dicts
        first_param = body["parameters"][0]
        assert "id" in first_param
        assert "current_level" in first_param

    def test_get_full_world(self, client):
        """GET /api/world/{id} returns the full world config (debugging endpoint)."""
        resp = client.get(f"/api/world/{DND_WORLD_ID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["world_id"] == DND_WORLD_ID
        assert "world_meta" in body
        assert "world_parameters" in body
        assert "npcs" in body
        assert "items" in body
        assert "locations" in body
        assert "eternal" in body
        assert "attitude_dimensions" in body


class TestGetWorldParameters:
    def test_get_world_parameters(self, client):
        """Verify the D&D 5e world has exactly 5 world parameters."""
        resp = client.get(f"/api/world/{DND_WORLD_ID}/parameters")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["world_id"] == DND_WORLD_ID
        assert body["count"] == 5
        assert len(body["parameters"]) == 5

        # Each entry has the required fields
        expected_ids = {
            "param_dragon_threat",
            "param_arcane_destabilization",
            "param_bandit_activity",
            "param_plague_spread",
            "param_political_tension",
        }
        seen_ids = {p["id"] for p in body["parameters"]}
        assert seen_ids == expected_ids, f"Got {seen_ids}, expected {expected_ids}"

        # Each param should expose name, current_level, and a non-empty levels list
        for p in body["parameters"]:
            assert isinstance(p["name"], str) and p["name"]
            assert isinstance(p["current_level"], int)
            assert 0 <= p["current_level"] <= 4
            assert isinstance(p["levels"], list) and len(p["levels"]) >= 2
            for lvl in p["levels"]:
                assert "level" in lvl
                assert "label" in lvl


class TestGetWorldStateCounts:
    def test_get_world_state_counts(self, client, dnd_yaml_data):
        """NPCs/items/locations counts returned by the API match the YAML."""
        resp = client.get(f"/api/world/{DND_WORLD_ID}/state")
        assert resp.status_code == 200
        body = resp.json()

        # Cross-check with raw YAML
        expected_npcs = len(dnd_yaml_data.get("npcs", []))
        expected_items = len(dnd_yaml_data.get("items", []))
        expected_locations = len(dnd_yaml_data.get("locations", []))

        assert body["npcs_count"] == expected_npcs, (
            f"npcs_count {body['npcs_count']} != yaml {expected_npcs}"
        )
        assert body["items_count"] == expected_items, (
            f"items_count {body['items_count']} != yaml {expected_items}"
        )
        assert body["locations_count"] == expected_locations, (
            f"locations_count {body['locations_count']} != yaml {expected_locations}"
        )

        # Sanity: there should be a non-trivial number of each
        assert body["npcs_count"] > 0
        assert body["items_count"] > 0
        assert body["locations_count"] > 0


class TestEtlTrigger:
    def test_etl_trigger(self, client):
        """POST /etl returns queued + an ISO 8601 timestamp; persisted on store."""
        resp = client.post(f"/api/world/{DND_WORLD_ID}/etl")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["world_id"] == DND_WORLD_ID
        assert body["status"] == "queued"

        # Timestamp should be ISO 8601 with Z suffix
        iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
        assert iso_re.match(body["etl_triggered_at"]), (
            f"Bad timestamp: {body['etl_triggered_at']}"
        )

        # Timestamp should also be persisted on the world record
        world = store.get_world(DND_WORLD_ID)
        assert world is not None
        assert world.get("last_etl_at") == body["etl_triggered_at"]
        assert world.get("last_etl_status") == "queued"
        # The etl_log should record this trigger
        assert isinstance(world.get("etl_log"), list)
        assert len(world["etl_log"]) >= 1
        last_log = world["etl_log"][-1]
        assert last_log["triggered_at"] == body["etl_triggered_at"]
        assert last_log["status"] == "queued"

    def test_etl_trigger_idempotent(self, client):
        """Triggering ETL twice records two log entries with distinct timestamps."""
        r1 = client.post(f"/api/world/{DND_WORLD_ID}/etl")
        r2 = client.post(f"/api/world/{DND_WORLD_ID}/etl")
        assert r1.status_code == 200
        assert r2.status_code == 200

        world = store.get_world(DND_WORLD_ID)
        assert len(world["etl_log"]) >= 2


class TestWorldNotFound:
    def test_world_not_found(self, client):
        """GET /state for a non-existent world_id → 404."""
        resp = client.get("/api/world/atlantis/state")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert "atlantis" in detail

    def test_world_not_found_parameters(self, client):
        """GET /parameters for a non-existent world_id → 404."""
        resp = client.get("/api/world/atlantis/parameters")
        assert resp.status_code == 404

    def test_world_not_found_etl(self, client):
        """POST /etl for a non-existent world_id → 404."""
        resp = client.post("/api/world/atlantis/etl")
        assert resp.status_code == 404
