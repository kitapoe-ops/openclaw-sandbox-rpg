"""
Unit tests for the scene API endpoints.

Covers:
- GET   /api/scene/{character_id}             current scene
- GET   /api/scene/{character_id}/history     history list
- POST  /api/scene/{character_id}/seed        seed a scene
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.store import store
from backend.api.character import router as character_router
from backend.api.scene import router as scene_router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_store():
    """Wipe the global in-memory store before each test for isolation."""
    store.characters.clear()
    store.scenes.clear()
    store.worlds.clear()
    yield
    store.characters.clear()
    store.scenes.clear()
    store.worlds.clear()


@pytest.fixture
def client():
    """FastAPI TestClient with character + scene routers mounted."""
    app = FastAPI()
    app.include_router(character_router, prefix="/api/character", tags=["character"])
    app.include_router(scene_router, prefix="/api/scene", tags=["scene"])
    return TestClient(app)


def _make_character(client, character_id: str = "char_001") -> None:
    """Helper: create a minimally-valid character via the public API."""
    payload = {
        "character_id": character_id,
        "name": f"Hero {character_id}",
        "world_id": "world_default",
        "physical": {"stamina_level": "fresh", "health_status": "healthy"},
        "mental": {"morale_level": "neutral"},
    }
    resp = client.post("/api/character/", json=payload)
    assert resp.status_code == 200, resp.text


def _minimal_seed_payload(round_no: int = 1, narrative: str = "A test scene") -> dict:
    """A minimally-valid scene seed body."""
    return {
        "round": round_no,
        "narrative": narrative,
        "choices": [
            {
                "id": "choice_advance",
                "description": "前進",
                "intent_category": "action",
                "attitude_options": [
                    {"dimension": "caution", "level": "balanced"},
                ],
            },
            {
                "id": "choice_wait",
                "description": "等待",
                "intent_category": "delay",
                "attitude_options": [
                    {"dimension": "caution", "level": "cautious"},
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestGetCurrentScene:
    def test_get_current_scene_empty(self, client):
        """Character exists but no scene seeded → 404."""
        _make_character(client, "char_empty")
        resp = client.get("/api/scene/char_empty")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        # Should reference the character_id
        assert "char_empty" in detail

    def test_get_current_scene_after_seed(self, client):
        """After seeding, GET returns the saved scene with all fields."""
        _make_character(client, "char_seed")

        seed_payload = _minimal_seed_payload(
            round_no=1,
            narrative="你站在酒館門口，夕陽把招牌染成紅色。",
        )
        seed_payload["minor_event"] = {
            "type": "atmospheric",
            "description": "遠處有狗在叫",
        }
        seed_payload["state_change_computed"] = {
            "stamina": {"old": "fresh", "new": "fresh", "delta": 0},
            "health": {"old": "healthy", "new": "healthy", "delta": 0},
            "morale": {"old": "neutral", "new": "calm", "delta": 0.2},
        }

        seed_resp = client.post("/api/scene/char_seed/seed", json=seed_payload)
        assert seed_resp.status_code == 200, seed_resp.text

        # Now GET /api/scene/char_seed
        get_resp = client.get("/api/scene/char_seed")
        assert get_resp.status_code == 200, get_resp.text
        body = get_resp.json()

        # Required scene_output fields
        assert body["round"] == 1
        assert body["character_id"] == "char_seed"
        assert body["narrative"] == "你站在酒館門口，夕陽把招牌染成紅色。"
        assert isinstance(body["choices"], list) and len(body["choices"]) == 2
        assert body["minor_event"]["description"] == "遠處有狗在叫"
        assert body["state_change_computed"]["morale"]["new"] == "calm"
        # state_changes should exist (defaulted to empty dict)
        assert "state_changes" in body

    def test_scene_404_character(self, client):
        """GET scene for a character that doesn't exist → 404."""
        resp = client.get("/api/scene/char_ghost")
        assert resp.status_code == 404
        assert "char_ghost" in resp.json()["detail"]


class TestGetSceneHistory:
    def test_get_scene_history(self, client):
        """Seed 3 scenes → GET /history?limit=2 returns the last 2 (oldest-first)."""
        _make_character(client, "char_hist")

        # Seed 3 scenes in order
        for r in (1, 2, 3):
            rseed = client.post(
                "/api/scene/char_hist/seed",
                json=_minimal_seed_payload(round_no=r, narrative=f"scene {r}"),
            )
            assert rseed.status_code == 200, rseed.text

        # History with limit=2 → newest 2 (rounds 2, 3) in that order
        resp = client.get("/api/scene/char_hist/history?limit=2")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["character_id"] == "char_hist"
        assert body["count"] == 2
        rounds = [s["round"] for s in body["scenes"]]
        assert rounds == [2, 3], f"Expected oldest-first [2,3], got {rounds}"

        # Sanity: each scene in history should have full schema
        for s in body["scenes"]:
            assert s["character_id"] == "char_hist"
            assert "narrative" in s
            assert "choices" in s

    def test_get_scene_history_default_limit(self, client):
        """No limit param → uses default 20; with 3 scenes returns all 3."""
        _make_character(client, "char_def")
        for r in (1, 2, 3):
            client.post(
                "/api/scene/char_def/seed",
                json=_minimal_seed_payload(round_no=r),
            )

        resp = client.get("/api/scene/char_def/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 3
        assert [s["round"] for s in body["scenes"]] == [1, 2, 3]

    def test_get_scene_history_404(self, client):
        """History on a non-existent character → 404."""
        resp = client.get("/api/scene/char_missing/history")
        assert resp.status_code == 404


class TestSeedScene:
    def test_seed_scene_via_api(self, client):
        """POST /seed stores the scene and returns it with created_at."""
        _make_character(client, "char_save")

        payload = _minimal_seed_payload(
            round_no=5,
            narrative="種子測試場景",
        )
        resp = client.post("/api/scene/char_save/seed", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["round"] == 5
        assert body["character_id"] == "char_save"
        assert body["narrative"] == "種子測試場景"
        # created_at should be ISO 8601 with Z suffix
        import re
        iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
        assert iso_re.match(body["created_at"]), f"Bad created_at: {body['created_at']}"

        # Round-trip: scene must actually be in the store
        latest = store.get_latest_scene("char_save")
        assert latest is not None
        assert latest["round"] == 5
        assert latest["narrative"] == "種子測試場景"

    def test_seed_scene_404_character(self, client):
        """POST /seed for non-existent character → 404."""
        payload = _minimal_seed_payload()
        resp = client.post("/api/scene/char_noone/seed", json=payload)
        assert resp.status_code == 404
        assert "char_noone" in resp.json()["detail"]

    def test_seed_scene_missing_fields(self, client):
        """POST /seed with missing required field → 400."""
        _make_character(client, "char_bad")
        # Drop 'narrative'
        bad_payload = {"round": 1, "choices": []}
        resp = client.post("/api/scene/char_bad/seed", json=bad_payload)
        assert resp.status_code == 400
        assert "narrative" in resp.json()["detail"]
