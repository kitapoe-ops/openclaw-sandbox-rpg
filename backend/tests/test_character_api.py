"""
Unit tests for the character API endpoints.

Covers:
- POST  /api/character/        create
- GET   /api/character/{id}    read
- PUT   /api/character/{id}    partial update
- GET   /api/character/        list
"""
import re
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.store import store
from backend.api.character import router as character_router


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
    """FastAPI TestClient bound to a minimal app that mounts the character router.

    We don't import the real `backend.main` because that triggers app-level
    WebSocket route registration, which is not needed for these unit tests
    and can fail on newer FastAPI versions.
    """
    app = FastAPI()
    app.include_router(character_router, prefix="/api/character", tags=["character"])
    return TestClient(app)


def _minimal_payload(character_id: str = "char_001", **overrides) -> dict:
    """A minimally-valid character body. Override individual keys as needed."""
    payload = {
        "character_id": character_id,
        "name": "Test Hero",
        "world_id": "world_default",
        "physical": {
            "stamina_level": "fresh",
            "health_status": "healthy",
        },
        "mental": {
            "morale_level": "neutral",
        },
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestCreateCharacter:
    def test_create_character_minimal(self, client):
        """POST with only required fields → defaults auto-filled correctly."""
        resp = client.post("/api/character/", json=_minimal_payload())
        assert resp.status_code == 200, resp.text

        body = resp.json()
        assert body["character_id"] == "char_001"
        assert body["name"] == "Test Hero"
        assert body["world_id"] == "world_default"
        assert body["physical"]["stamina_level"] == "fresh"
        assert body["physical"]["health_status"] == "healthy"
        assert body["physical"]["active_effects"] == []  # auto-filled
        assert body["mental"]["morale_level"] == "neutral"
        assert body["memories"] == []  # auto-filled
        assert body["current_location"] == ""  # auto-filled default

        # created_at / updated_at should be ISO 8601 with Z suffix
        iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
        assert iso_re.match(body["created_at"]), f"Bad created_at: {body['created_at']}"
        assert iso_re.match(body["updated_at"]), f"Bad updated_at: {body['updated_at']}"

    def test_create_character_full(self, client):
        """POST with all fields → stored as-is (no clobbering)."""
        full = {
            "character_id": "char_full",
            "name": "Full Hero",
            "world_id": "world_full",
            "created_at": "2026-01-01T00:00:00Z",  # user-supplied
            "physical": {
                "stamina_level": "exhausted",
                "health_status": "wounded",
                "active_effects": ["左臂骨折", "左肩脫臼"],
            },
            "mental": {
                "morale_level": "anxious",
                "alertness_level": "distracted",
                "emotional_state": "tense",
            },
            "attitude": {"caution": "balanced", "aggression": "cautious"},
            "inventory": {
                "items": [{"item_id": "item_sword", "quantity": 1}],
                "carrying_weight": "light",
            },
            "memories": ["首戰回憶"],
            "current_location": "loc_cave_01",
        }
        resp = client.post("/api/character/", json=full)
        assert resp.status_code == 200, resp.text

        body = resp.json()
        assert body["physical"]["stamina_level"] == "exhausted"
        assert body["physical"]["active_effects"] == ["左臂骨折", "左肩脫臼"]
        assert body["mental"]["morale_level"] == "anxious"
        assert body["mental"]["alertness_level"] == "distracted"
        assert body["memories"] == ["首戰回憶"]
        assert body["current_location"] == "loc_cave_01"
        # user-supplied created_at preserved
        assert body["created_at"] == "2026-01-01T00:00:00Z"

    def test_create_character_invalid_enum(self, client):
        """POST with bad stamina_level → 400."""
        bad = _minimal_payload(character_id="char_bad")
        bad["physical"]["stamina_level"] = "very_tired"  # not in enum
        resp = client.post("/api/character/", json=bad)
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "errors" in detail
        assert any("stamina_level" in e for e in detail["errors"])

    def test_create_character_duplicate(self, client):
        """POST same id twice → second returns 409."""
        client.post("/api/character/", json=_minimal_payload("char_dup"))
        resp = client.post("/api/character/", json=_minimal_payload("char_dup"))
        assert resp.status_code == 409
        assert "char_dup" in resp.json()["detail"]


class TestGetCharacter:
    def test_get_character(self, client):
        """POST then GET → same data."""
        create_resp = client.post(
            "/api/character/",
            json=_minimal_payload("char_get", name="GetMe"),
        )
        assert create_resp.status_code == 200
        created = create_resp.json()

        get_resp = client.get("/api/character/char_get")
        assert get_resp.status_code == 200
        fetched = get_resp.json()

        # Same core fields
        assert fetched["character_id"] == created["character_id"]
        assert fetched["name"] == created["name"]
        assert fetched["world_id"] == created["world_id"]
        assert fetched["physical"] == created["physical"]
        assert fetched["mental"] == created["mental"]

    def test_get_character_not_found(self, client):
        """GET nonexistent id → 404."""
        resp = client.get("/api/character/char_ghost")
        assert resp.status_code == 404
        assert "char_ghost" in resp.json()["detail"]


class TestUpdateCharacter:
    def test_update_character_name(self, client):
        """PUT name → returns updated character with new name."""
        client.post("/api/character/", json=_minimal_payload("char_upd"))
        resp = client.put("/api/character/char_upd", json={"name": "Renamed Hero"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "Renamed Hero"
        # Other fields preserved
        assert body["character_id"] == "char_upd"
        assert body["world_id"] == "world_default"
        # updated_at should be set
        assert body.get("updated_at")

    def test_update_character_invalid_field(self, client):
        """PUT with a non-allowed field → 400."""
        client.post("/api/character/", json=_minimal_payload("char_inv"))
        resp = client.put(
            "/api/character/char_inv",
            json={"secret_password": "hack"},  # not in whitelist
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "errors" in detail
        assert any("secret_password" in e for e in detail["errors"])

    def test_update_character_not_found(self, client):
        """PUT on nonexistent character → 404."""
        resp = client.put(
            "/api/character/char_nope",
            json={"name": "Whatever"},
        )
        assert resp.status_code == 404
        assert "char_nope" in resp.json()["detail"]

    def test_update_character_stamina(self, client):
        """Extra coverage: stamina_level update with valid enum passes."""
        client.post("/api/character/", json=_minimal_payload("char_stam"))
        resp = client.put(
            "/api/character/char_stam",
            json={"physical.stamina_level": "muscle_ache"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["physical"]["stamina_level"] == "muscle_ache"

    def test_update_character_stamina_invalid(self, client):
        """Extra coverage: invalid stamina value on update → 400."""
        client.post("/api/character/", json=_minimal_payload("char_bads"))
        resp = client.put(
            "/api/character/char_bads",
            json={"physical.stamina_level": "hyperactive"},
        )
        assert resp.status_code == 400
        assert any("stamina_level" in e for e in resp.json()["detail"]["errors"])


class TestListCharacters:
    def test_list_characters(self, client):
        """POST 3 characters → list returns all 3."""
        for cid in ("char_a", "char_b", "char_c"):
            client.post("/api/character/", json=_minimal_payload(cid))

        resp = client.get("/api/character/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 3
        ids = {c["character_id"] for c in body["characters"]}
        assert ids == {"char_a", "char_b", "char_c"}

    def test_list_characters_empty(self, client):
        """No characters → list returns count=0."""
        resp = client.get("/api/character/")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
        assert resp.json()["characters"] == []
