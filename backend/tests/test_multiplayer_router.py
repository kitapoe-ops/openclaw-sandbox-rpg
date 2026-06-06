"""
Phase E6a — Multiplayer WebSocket fan-out router tests (8/8)
============================================================

Covers the new ``backend.ws.multiplayer_router.MultiplayerConnectionManager``
and the FastAPI routes registered on the composed app
(``backend.app_with_memory.app``).

All tests are **hermetic** — no Postgres, no real LLM, no real
WebSocket client. We use ``AsyncMock`` from the standard library
to fake the FastAPI ``WebSocket`` object (it only needs
``send_json`` and ``receive_json`` for the manager; the route
tests use the ``ASGITransport`` + ``AsyncClient`` pattern from
:mod:`backend.tests.test_action_processor`).

Test inventory (8/8):
    1.  test_connect_succeeds_for_first_player
    2.  test_connect_returns_false_when_scene_full
    3.  test_disconnect_removes_player
    4.  test_broadcast_to_scene_sends_to_all_players
    5.  test_broadcast_excludes_sender
    6.  test_send_to_player_only_delivers_to_target
    7.  test_health_reports_stats
    8.  test_concurrent_connects_serialized
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

# Ensure repo root on sys.path (same idiom as other backend tests).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.ws.multiplayer_router import (  # noqa: E402
    MultiplayerConnectionManager,
    get_multiplayer_manager,
    multiplayer_ws_endpoint,
)
from backend.ws.multiplayer_router import (
    multiplayer_manager as default_manager,
)

# ============================================
# Fixtures
# ============================================


def make_fake_ws() -> AsyncMock:
    """Build an AsyncMock that mimics a FastAPI WebSocket.

    Only ``send_json`` is exercised by the manager; we add
    ``accept`` and ``close`` for the route tests, and
    ``receive_json`` to drive the WS endpoint loop.
    """
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.receive_json = AsyncMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    return ws


@pytest_asyncio.fixture
async def manager() -> MultiplayerConnectionManager:
    """Yield a fresh manager per-test. We do NOT touch the
    module-level singleton to keep tests isolated — see
    ``manager_with_singleton`` for the singleton variant.
    """
    mgr = MultiplayerConnectionManager(max_players_per_scene=4)
    return mgr


# ============================================
# 1. test_connect_succeeds_for_first_player
# ============================================


@pytest.mark.asyncio
async def test_connect_succeeds_for_first_player(manager):
    """Single connect, verify stored, health reflects it."""
    ws = make_fake_ws()
    ok = await manager.connect("scene_1", "player_a", ws)
    assert ok is True
    assert manager.get_connected_players("scene_1") == ["player_a"]
    assert manager.get_total_connection_count() == 1
    assert manager.get_scene_count() == 1
    # No broadcast yet
    health = manager.health()
    assert health["active_scenes"] == 1
    assert health["total_connections"] == 1
    assert health["max_players_per_scene"] == 4
    assert health["lifetime"]["total_connects"] == 1


# ============================================
# 2. test_connect_returns_false_when_scene_full
# ============================================


@pytest.mark.asyncio
async def test_connect_returns_false_when_scene_full(manager):
    """4 connects succeed; 5th returns False (capacity cap)."""
    sockets = [make_fake_ws() for _ in range(5)]
    player_ids = [f"player_{i}" for i in range(5)]

    # First 4 must succeed
    for i in range(4):
        ok = await manager.connect("scene_1", player_ids[i], sockets[i])
        assert ok is True, f"player_{i} should have connected"

    # 5th must fail
    ok = await manager.connect("scene_1", player_ids[4], sockets[4])
    assert ok is False, "5th player must be rejected (cap=4)"

    # State check
    assert manager.get_total_connection_count() == 4
    assert sorted(manager.get_connected_players("scene_1")) == sorted(player_ids[:4])

    # Lifetime counter: only the 4 successful connects counted
    assert manager.health()["lifetime"]["total_connects"] == 4


# ============================================
# 3. test_disconnect_removes_player
# ============================================


@pytest.mark.asyncio
async def test_disconnect_removes_player(manager):
    """Connect + disconnect → player removed; empty scene is GC'd."""
    ws = make_fake_ws()
    await manager.connect("scene_x", "player_alice", ws)
    assert manager.get_connected_players("scene_x") == ["player_alice"]

    await manager.disconnect("scene_x", "player_alice")
    assert manager.get_connected_players("scene_x") == []
    # Empty scene is garbage-collected
    assert manager.get_scene_count() == 0
    assert manager.get_total_connection_count() == 0
    assert manager.health()["lifetime"]["total_disconnects"] == 1

    # Idempotent: second disconnect is a no-op
    await manager.disconnect("scene_x", "player_alice")
    assert manager.health()["lifetime"]["total_disconnects"] == 1


# ============================================
# 4. test_broadcast_to_scene_sends_to_all_players
# ============================================


@pytest.mark.asyncio
async def test_broadcast_to_scene_sends_to_all_players(manager):
    """3 players, broadcast a message, all 3 receive it."""
    sockets = {f"p{i}": make_fake_ws() for i in range(1, 4)}
    for pid, ws in sockets.items():
        await manager.connect("scene_3p", pid, ws)

    message = {"event": "npc_action", "actor": "npc_gundren", "narrative": "hi"}
    count = await manager.broadcast_to_scene("scene_3p", message)
    assert count == 3

    for pid, ws in sockets.items():
        ws.send_json.assert_awaited_once_with(message)

    # Lifetime tally
    health = manager.health()
    assert health["lifetime"]["total_broadcasts"] == 1
    assert health["lifetime"]["total_broadcast_recipients"] == 3


# ============================================
# 5. test_broadcast_excludes_sender
# ============================================


@pytest.mark.asyncio
async def test_broadcast_excludes_sender(manager):
    """3 players, broadcast with exclude=player_1 → only 2 + 3 receive."""
    sockets = {f"player_{i}": make_fake_ws() for i in range(1, 4)}
    for pid, ws in sockets.items():
        await manager.connect("scene_3p", pid, ws)

    message = {"event": "player_action", "from": "player_1"}
    count = await manager.broadcast_to_scene("scene_3p", message, exclude="player_1")
    assert count == 2

    # player_1 was excluded — its send_json must NOT have been called
    sockets["player_1"].send_json.assert_not_awaited()
    # player_2 and player_3 each got it once
    sockets["player_2"].send_json.assert_awaited_once_with(message)
    sockets["player_3"].send_json.assert_awaited_once_with(message)


# ============================================
# 6. test_send_to_player_only_delivers_to_target
# ============================================


@pytest.mark.asyncio
async def test_send_to_player_only_delivers_to_target(manager):
    """3 players, send_to_player(p2) → only p2 receives."""
    sockets = {f"player_{i}": make_fake_ws() for i in range(1, 4)}
    for pid, ws in sockets.items():
        await manager.connect("scene_3p", pid, ws)

    message = {"event": "private_whisper", "from": "npc_gundren"}
    ok = await manager.send_to_player("scene_3p", "player_2", message)
    assert ok is True

    # Only player_2 received it
    sockets["player_2"].send_json.assert_awaited_once_with(message)
    sockets["player_1"].send_json.assert_not_awaited()
    sockets["player_3"].send_json.assert_not_awaited()

    # send to non-existent player returns False
    ok2 = await manager.send_to_player("scene_3p", "player_ghost", message)
    assert ok2 is False


# ============================================
# 7. test_health_reports_stats
# ============================================


@pytest.mark.asyncio
async def test_health_reports_stats(manager):
    """2 scenes × 2 players = 4 connections. Health reflects exactly that."""
    # Scene A: 2 players
    for i in range(2):
        await manager.connect("scene_A", f"A_p{i}", make_fake_ws())
    # Scene B: 2 players
    for i in range(2):
        await manager.connect("scene_B", f"B_p{i}", make_fake_ws())

    health = manager.health()
    assert health["active_scenes"] == 2
    assert health["total_connections"] == 4
    assert health["max_players_per_scene"] == 4
    assert sorted(health["by_scene"].keys()) == ["scene_A", "scene_B"]
    assert health["by_scene"]["scene_A"]["player_count"] == 2
    assert health["by_scene"]["scene_B"]["player_count"] == 2
    assert sorted(health["by_scene"]["scene_A"]["players"]) == ["A_p0", "A_p1"]
    # Lifetime
    assert health["lifetime"]["total_connects"] == 4
    assert health["lifetime"]["total_disconnects"] == 0
    assert health["lifetime"]["uptime_seconds"] >= 0

    # Lock-free inspection methods agree
    assert manager.get_scene_count() == 2
    assert manager.get_total_connection_count() == 4
    assert sorted(manager.get_connected_players("scene_A")) == ["A_p0", "A_p1"]
    assert manager.get_connected_players("nonexistent") == []


# ============================================
# 8. test_concurrent_connects_serialized
# ============================================


@pytest.mark.asyncio
async def test_concurrent_connects_serialized(manager):
    """Race 4 concurrent connects → exactly 4 succeed, 5th is rejected.

    The per-scene lock must serialize the capacity check so
    that two simultaneous attempts that *both* see "3/4" do
    not both squeeze in. We start with 3 players and fire
    two concurrent connects — only one should win, leaving
    the scene at 4/4. Then a fifth concurrent connect is
    rejected outright.
    """
    # Seed 3 players
    for i in range(3):
        await manager.connect("scene_race", f"seed_{i}", make_fake_ws())

    # Two concurrent connects for the last slot
    ws_a = make_fake_ws()
    ws_b = make_fake_ws()
    res_a, res_b = await asyncio.gather(
        manager.connect("scene_race", "racer_a", ws_a),
        manager.connect("scene_race", "racer_b", ws_b),
    )
    winners = [res_a, res_b]
    assert (
        winners.count(True) == 1
    ), f"Expected exactly 1 winner in the race, got {winners.count(True)}"
    assert winners.count(False) == 1

    # Scene should be at 4/4 exactly
    assert manager.get_total_connection_count() == 4
    assert len(manager.get_connected_players("scene_race")) == 4

    # Fifth concurrent connect is rejected
    ws_c = make_fake_ws()
    ok = await manager.connect("scene_race", "racer_c", ws_c)
    assert ok is False
    assert manager.get_total_connection_count() == 4


# ============================================
# Bonus (not in brief but cheap): route-level smoke
# ============================================
# The brief asks for 6-8 tests; we shipped 8 above. The two
# tests below exercise the FastAPI HTTP routes on the composed
# app to confirm the wire-up in ``app_with_memory.py`` works
# end-to-end (hermetic, no real WS client). They live here so
# the regression suite catches a future refactor that breaks
# the route table.


@pytest_asyncio.fixture
async def http_client():
    """ASGI client against the composed app — mirrors the E1
    test pattern. The lifespan is short-circuited because the
    composed app's lifespan opens Postgres; we want hermetic.
    """
    from httpx import ASGITransport, AsyncClient

    from backend.app_with_memory import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_http_broadcast_endpoint_reports_zero_when_no_players(http_client):
    """POST /api/multiplayer/{scene_id}/broadcast with no connected
    players returns ``delivered_to: 0`` — the route does not 404
    on an empty scene, it just reports the count.
    """
    # Use a unique scene_id to avoid coupling with the singleton
    # state from other tests in this run.
    scene_id = "scene_http_smoke_empty"
    resp = await http_client.post(
        f"/api/multiplayer/{scene_id}/broadcast",
        json={"event": "smoke", "narrative": "hello"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["scene_id"] == scene_id
    assert body["delivered_to"] == 0


@pytest.mark.asyncio
async def test_http_multiplayer_health_endpoint_returns_dict(http_client):
    """GET /api/multiplayer/health returns the manager.health() shape."""
    resp = await http_client.get("/api/multiplayer/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "active_scenes" in body
    assert "total_connections" in body
    assert "max_players_per_scene" in body
    assert "by_scene" in body
    assert "lifetime" in body
