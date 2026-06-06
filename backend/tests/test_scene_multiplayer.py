"""
Phase E6b — Multiplayer scene state + memory isolation tests
=============================================================

Covers the new modules shipped in Phase E6b:

* :mod:`backend.scene_multiplayer`
    - :class:`MultiplayerScene` — per-scene state (players, NPCs, turn queue)
    - :class:`SceneRegistry` — process-local scene holder
* :mod:`backend.memory_isolation`
    - :class:`MemoryIsolationGuard` — per-scene memory access control
    - :class:`_IsolatedMemoryPalace` — proxy that enforces isolation
* HTTP routes registered on ``backend.app_with_memory.app`` (E6b)

All tests are **hermetic** — no Postgres, no real LLM, no real
WebSocket. The HTTP route tests use the ``ASGITransport`` +
``AsyncClient`` pattern from
:mod:`backend.tests.test_action_processor`.

Test inventory (15):

    MultiplayerScene (10)
    -----------------
     1.  test_add_player_succeeds_for_first_player
     2.  test_add_player_returns_false_when_scene_full
     3.  test_remove_player_cleans_up_state
     4.  test_add_npc_returns_false_when_scene_full
     5.  test_turn_queue_processes_in_order
     6.  test_memory_isolation_player_can_read_own
     7.  test_memory_isolation_player_cannot_read_other_player
     8.  test_memory_isolation_player_can_read_npc
     9.  test_health_reports_all_stats
    10.  test_concurrent_add_player_serialized

    MemoryIsolationGuard (5)
    -----------------------
    11.  test_authorize_own_character
    12.  test_authorize_other_character_denied
    13.  test_authorize_npc_character_allowed
    14.  test_authorize_unknown_scene_denied
    15.  test_wrap_memory_palace_blocks_unauthorized
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Ensure repo root on sys.path (same idiom as other backend tests).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.memory_isolation import (  # noqa: E402
    MemoryIsolationError,
    MemoryIsolationGuard,
    get_isolation_guard,
    isolation_guard,
)
from backend.scene_multiplayer import (  # noqa: E402
    DEFAULT_MAX_NPCS_PER_SCENE,
    DEFAULT_MAX_PLAYERS_PER_SCENE,
    MultiplayerScene,
    SceneRegistry,
    get_scene_registry,
    scene_registry,
)

# ============================================
# Fixtures
# ============================================


@pytest.fixture
def fresh_registry() -> SceneRegistry:
    """A fresh ``SceneRegistry`` for tests that should not share state."""
    return SceneRegistry()


@pytest.fixture
def fresh_guard(fresh_registry: SceneRegistry) -> MemoryIsolationGuard:
    """A fresh ``MemoryIsolationGuard`` bound to ``fresh_registry``."""
    return MemoryIsolationGuard(scene_registry=fresh_registry)


# ============================================
# MultiplayerScene tests
# ============================================


@pytest.mark.asyncio
async def test_add_player_succeeds_for_first_player() -> None:
    """Single add: returns True, state stored, snapshot reflects it."""
    scene = MultiplayerScene("s1")
    assert await scene.add_player("p1", "char_alice") is True
    players = scene.get_players()
    assert len(players) == 1
    assert players[0].player_id == "p1"
    assert players[0].character_id == "char_alice"
    assert players[0].alive is True
    assert players[0].turn_position == 0


@pytest.mark.asyncio
async def test_add_player_returns_false_when_scene_full() -> None:
    """5th player rejected (cap = 4)."""
    scene = MultiplayerScene("s1", max_players=4)
    for i in range(4):
        ok = await scene.add_player(f"p{i+1}", f"char_{i+1}")
        assert ok is True, f"player {i+1} should have been added"
    # 5th rejected
    ok5 = await scene.add_player("p5", "char_5")
    assert ok5 is False
    assert len(scene.get_players()) == 4


@pytest.mark.asyncio
async def test_remove_player_cleans_up_state() -> None:
    """add + remove: state goes to 0, idempotent on second remove."""
    scene = MultiplayerScene("s1")
    assert await scene.add_player("p1", "char_alice") is True
    assert len(scene.get_players()) == 1
    await scene.remove_player("p1")
    assert len(scene.get_players()) == 0
    # Idempotent: removing again is a no-op, no error.
    await scene.remove_player("p1")
    assert len(scene.get_players()) == 0
    # Removing a never-added player is also a no-op.
    await scene.remove_player("ghost")
    assert len(scene.get_players()) == 0


@pytest.mark.asyncio
async def test_add_npc_returns_false_when_scene_full() -> None:
    """NPC cap = 100. 100 adds succeed, 101st returns False."""
    scene = MultiplayerScene("s1", max_npcs=100)
    for i in range(100):
        ok = await scene.add_npc(
            npc_id=f"npc_{i+1}",
            character_id=f"char_npc_{i+1}",
            location="loc_tavern",
        )
        assert ok is True, f"npc {i+1} should have been added"
    # 101st rejected
    ok101 = await scene.add_npc(
        npc_id="npc_101", character_id="char_npc_101", location="loc_tavern"
    )
    assert ok101 is False
    assert len(scene.get_npcs()) == 100
    # And the default cap constant matches
    assert DEFAULT_MAX_NPCS_PER_SCENE == 100
    assert DEFAULT_MAX_PLAYERS_PER_SCENE == 4


@pytest.mark.asyncio
async def test_turn_queue_processes_in_order() -> None:
    """FIFO: 3 enqueues → process_next_turn returns them in order."""
    scene = MultiplayerScene("s1")
    await scene.add_player("p1", "char_alice")
    t1 = await scene.enqueue_action("p1", {"verb": "look"})
    t2 = await scene.enqueue_action("p1", {"verb": "speak", "target": "npc_x"})
    t3 = await scene.enqueue_action("p1", {"verb": "move", "target": "door"})
    assert scene.get_turn_queue_size() == 3

    first = await scene.process_next_turn()
    second = await scene.process_next_turn()
    third = await scene.process_next_turn()

    assert first is not None and first.ticket_id == t1
    assert first.action["verb"] == "look"
    assert second is not None and second.ticket_id == t2
    assert second.action["verb"] == "speak"
    assert third is not None and third.ticket_id == t3
    assert third.action["verb"] == "move"

    # Queue empty: process_next_turn returns None (non-blocking).
    fourth = await scene.process_next_turn()
    assert fourth is None
    assert scene.get_turn_queue_size() == 0


@pytest.mark.asyncio
async def test_memory_isolation_player_can_read_own() -> None:
    """Player can always read their own character memory."""
    scene = MultiplayerScene("s1")
    await scene.add_player("p_alice", "char_alice")
    assert scene.can_read_memory("p_alice", "char_alice") is True
    # And write to own (write is stricter but own-own is allowed).
    assert scene.can_write_memory("p_alice", "char_alice") is True


@pytest.mark.asyncio
async def test_memory_isolation_player_cannot_read_other_player() -> None:
    """THE CRITICAL TEST: Player A cannot read Player B's memory.

    This is the security invariant. We assert it returns ``False``
    explicitly (not just "not True") so a future refactor that
    accidentally returns ``None`` would still fail the test.
    """
    scene = MultiplayerScene("s1")
    await scene.add_player("p_alice", "char_alice")
    await scene.add_player("p_bob", "char_bob")
    # p_alice tries to read p_bob's character memory
    assert scene.can_read_memory("p_alice", "char_bob") is False
    # Symmetric: p_bob tries to read p_alice's
    assert scene.can_read_memory("p_bob", "char_alice") is False
    # And the stricter write rule: both denied
    assert scene.can_write_memory("p_alice", "char_bob") is False
    assert scene.can_write_memory("p_bob", "char_alice") is False


@pytest.mark.asyncio
async def test_memory_isolation_player_can_read_npc() -> None:
    """NPC memories are shared canon: any player may read them.

    The NPC is matched by both ``npc_id`` and the NPC's
    ``character_id`` — a player doesn't have to know which
    identifier the NPC was registered under.
    """
    scene = MultiplayerScene("s1")
    await scene.add_player("p_alice", "char_alice")
    await scene.add_npc(
        npc_id="npc_gundren",
        character_id="char_gundren",
        location="loc_tavern",
    )
    # Read by character_id (the way a frontend would look it up)
    assert scene.can_read_memory("p_alice", "char_gundren") is True
    # Read by npc_id (the way the scene object looks it up)
    assert scene.can_read_memory("p_alice", "npc_gundren") is True
    # Writes to NPC memory are still denied (NPCs are managed by
    # the action pipeline, not by players).
    assert scene.can_write_memory("p_alice", "char_gundren") is False


@pytest.mark.asyncio
async def test_health_reports_all_stats() -> None:
    """Health dict has every documented field, counts match state."""
    scene = MultiplayerScene("s1", max_players=4, max_npcs=100)
    await scene.add_player("p_alice", "char_alice")
    await scene.add_player("p_bob", "char_bob")
    await scene.add_npc("npc_gundren", "char_gundren", "loc_tavern")
    await scene.enqueue_action("p_alice", {"verb": "look"})

    h = scene.health()
    # All required fields present
    for key in (
        "scene_id",
        "player_count",
        "npc_count",
        "alive_count",
        "alive_players",
        "alive_npcs",
        "queue_size",
        "max_players",
        "max_npcs",
        "uptime_seconds",
    ):
        assert key in h, f"missing health key: {key}"
    assert h["scene_id"] == "s1"
    assert h["player_count"] == 2
    assert h["npc_count"] == 1
    assert h["alive_players"] == 2
    assert h["alive_npcs"] == 1
    assert h["alive_count"] == 3
    assert h["queue_size"] == 1
    assert h["max_players"] == 4
    assert h["max_npcs"] == 100
    assert h["uptime_seconds"] >= 0.0


@pytest.mark.asyncio
async def test_concurrent_add_player_serialized() -> None:
    """8 concurrent adds with cap=4 → exactly 4 succeed, 4 fail.

    This is the lock-correctness test. Without the per-scene
    lock, two simultaneous adds would both pass the capacity
    check (``len() < 4``) and the scene would overflow.
    """
    scene = MultiplayerScene("s1", max_players=4)
    results = await asyncio.gather(*[scene.add_player(f"p{i}", f"char_{i}") for i in range(8)])
    succeeded = sum(1 for r in results if r is True)
    failed = sum(1 for r in results if r is False)
    assert succeeded == 4, f"expected exactly 4 successes, got {succeeded}"
    assert failed == 4, f"expected exactly 4 failures, got {failed}"
    assert len(scene.get_players()) == 4


# ============================================
# MemoryIsolationGuard tests
# ============================================


@pytest.mark.asyncio
async def test_authorize_own_character(
    fresh_guard: MemoryIsolationGuard,
    fresh_registry: SceneRegistry,
) -> None:
    """Guard: requester may read+write their own character."""
    scene = await fresh_registry.get_or_create("s1")
    await scene.add_player("p_alice", "char_alice")
    assert fresh_guard.authorize("p_alice", "s1", "char_alice", op="read") is True
    assert fresh_guard.authorize("p_alice", "s1", "char_alice", op="write") is True
    # And ``require()`` does not raise.
    fresh_guard.require("p_alice", "s1", "char_alice", op="read")


@pytest.mark.asyncio
async def test_authorize_other_character_denied(
    fresh_guard: MemoryIsolationGuard,
    fresh_registry: SceneRegistry,
) -> None:
    """Guard: requester denied read+write on another player's char.

    Critically, the write rule is also denied — even if some
    future code path accidentally exposes a write to a
    requester who is not the controller, the guard refuses.
    """
    scene = await fresh_registry.get_or_create("s1")
    await scene.add_player("p_alice", "char_alice")
    await scene.add_player("p_bob", "char_bob")
    assert fresh_guard.authorize("p_alice", "s1", "char_bob", op="read") is False
    assert fresh_guard.authorize("p_alice", "s1", "char_bob", op="write") is False
    # ``require()`` raises MemoryIsolationError (subclass of PermissionError).
    with pytest.raises(MemoryIsolationError):
        fresh_guard.require("p_alice", "s1", "char_bob", op="read")
    with pytest.raises(MemoryIsolationError):
        fresh_guard.require("p_alice", "s1", "char_bob", op="write")


@pytest.mark.asyncio
async def test_authorize_npc_character_allowed(
    fresh_guard: MemoryIsolationGuard,
    fresh_registry: SceneRegistry,
) -> None:
    """Guard: any player may READ an NPC; writes are still denied."""
    scene = await fresh_registry.get_or_create("s1")
    await scene.add_player("p_alice", "char_alice")
    await scene.add_npc("npc_x", "char_x", "loc_tavern")
    assert fresh_guard.authorize("p_alice", "s1", "char_x", op="read") is True
    # Writes to NPC are denied (only the DM/action pipeline can
    # write to NPC memories, not players).
    assert fresh_guard.authorize("p_alice", "s1", "char_x", op="write") is False
    with pytest.raises(MemoryIsolationError):
        fresh_guard.require("p_alice", "s1", "char_x", op="write")


@pytest.mark.asyncio
async def test_authorize_unknown_scene_denied(
    fresh_guard: MemoryIsolationGuard,
) -> None:
    """Guard: unknown scene → fail-closed, ``require()`` raises."""
    # Scene does not exist
    assert fresh_guard.authorize("p_alice", "ghost_scene", "char_x", op="read") is False
    # Empty / None inputs are also denied.
    assert fresh_guard.authorize("", "s1", "char_x", op="read") is False
    assert fresh_guard.authorize("p_alice", "", "char_x", op="read") is False
    assert fresh_guard.authorize("p_alice", "s1", "", op="read") is False
    # require() raises
    with pytest.raises(MemoryIsolationError):
        fresh_guard.require("p_alice", "ghost_scene", "char_x", op="read")


@pytest.mark.asyncio
async def test_wrap_memory_palace_blocks_unauthorized() -> None:
    """Wrapped palace: cross-character access raises PermissionError.

    We build a stub palace (AsyncMock-shaped) and verify:

      * Own-character ``remember`` is allowed (the underlying
        stub is called).
      * Other-character ``remember`` raises
        :class:`MemoryIsolationError` (the underlying stub is
        NOT called).
    """

    # Stub memory palace with the same surface as Phase A +
    # Phase C2. AsyncMock auto-creates attributes on access.
    class StubPalace:
        def __init__(self) -> None:
            self.remember = AsyncMock(return_value={"ok": True})
            self.recall = AsyncMock(return_value=["mem1", "mem2"])
            self.forget = AsyncMock(return_value=True)
            self.add_memory = AsyncMock(return_value="frag-uuid")
            self.get_memories = AsyncMock(return_value=["a", "b"])
            self.health = AsyncMock(return_value={"ok": True})

    registry = SceneRegistry()
    scene = await registry.get_or_create("s1")
    await scene.add_player("p_alice", "char_alice")
    await scene.add_player("p_bob", "char_bob")
    guard = MemoryIsolationGuard(scene_registry=registry)

    stub = StubPalace()
    wrapped = guard.wrap_memory_palace(stub, scene_id="s1", requester_id="p_alice")

    # Own-character write: passes through, stub is called once.
    res = await wrapped.remember("char_alice", content="hello")
    assert res == {"ok": True}
    assert stub.remember.await_count == 1

    # Own-character read: passes through, stub is called once.
    items = await wrapped.recall("char_alice", query="anything")
    assert items == ["mem1", "mem2"]
    assert stub.recall.await_count == 1

    # Other-character write: BLOCKED. PermissionError subclass.
    with pytest.raises(MemoryIsolationError):
        await wrapped.remember("char_bob", content="leak attempt")
    # Critical: stub was NOT called.
    assert stub.remember.await_count == 1  # unchanged

    # Other-character read: BLOCKED.
    with pytest.raises(MemoryIsolationError):
        await wrapped.recall("char_bob", query="anything")
    assert stub.recall.await_count == 1  # unchanged

    # Other-character forget: BLOCKED.
    with pytest.raises(MemoryIsolationError):
        await wrapped.forget("char_bob", memory_id="m1")
    assert stub.forget.await_count == 0  # never called

    # Phase A's add_memory: BLOCKED for cross-character.
    with pytest.raises(MemoryIsolationError):
        await wrapped.add_memory("char_bob", content="x")
    assert stub.add_memory.await_count == 0

    # Phase A's get_memories: BLOCKED for cross-character.
    with pytest.raises(MemoryIsolationError):
        await wrapped.get_memories("char_bob")
    assert stub.get_memories.await_count == 0

    # Passthrough: non-intercepted methods (e.g. ``health``) work
    # unchanged. ``__getattr__`` delegates to the inner stub.
    h = await wrapped.health()
    assert h == {"ok": True}


# ============================================
# HTTP route smoke tests (use ASGITransport; no live server)
# ============================================


@pytest_asyncio.fixture
async def http_client():
    """An ``httpx.AsyncClient`` wired to the composed app in-process.

    The E6b routes are mounted on ``backend.app_with_memory.app``;
    this fixture does NOT start uvicorn — it uses
    ``ASGITransport`` so requests go straight to the ASGI app.
    """
    from backend.app_with_memory import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_http_create_and_join_scene_end_to_end(
    http_client: AsyncClient,
) -> None:
    """End-to-end: create scene → join → list players → leave.

    Exercises the actual FastAPI wire-up, not just the unit
    functions. Uses a unique scene id so it doesn't collide
    with other tests that share the module-level registry.
    """
    scene_id = "http_smoke_scene_1"

    # Create
    r = await http_client.post(
        f"/api/scene-multiplayer/{scene_id}/create",
        params={"max_players": 4, "max_npcs": 100},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scene_id"] == scene_id
    assert body["player_count"] == 0
    assert body["npc_count"] == 0

    # Join player 1
    r = await http_client.post(
        f"/api/scene-multiplayer/{scene_id}/player/p1/join",
        params={"character_id": "char_alice"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["player_count"] == 1

    # Join player 2
    r = await http_client.post(
        f"/api/scene-multiplayer/{scene_id}/player/p2/join",
        params={"character_id": "char_bob"},
    )
    assert r.status_code == 200
    assert r.json()["player_count"] == 2

    # List players
    r = await http_client.get(f"/api/scene-multiplayer/{scene_id}/players")
    assert r.status_code == 200
    listing = r.json()
    assert listing["count"] == 2
    pids = {p["player_id"] for p in listing["players"]}
    assert pids == {"p1", "p2"}

    # Leave player 1
    r = await http_client.post(f"/api/scene-multiplayer/{scene_id}/player/p1/leave")
    assert r.status_code == 200
    assert r.json()["removed"] is True

    # List → 1 player left
    r = await http_client.get(f"/api/scene-multiplayer/{scene_id}/players")
    assert r.json()["count"] == 1


@pytest.mark.asyncio
async def test_http_turn_queue_roundtrip(
    http_client: AsyncClient,
) -> None:
    """Enqueue 2 actions, then process 2 — order preserved, queue drains."""
    scene_id = "http_turn_scene_1"

    # Create + add player
    await http_client.post(f"/api/scene-multiplayer/{scene_id}/create")
    await http_client.post(
        f"/api/scene-multiplayer/{scene_id}/player/p1/join",
        params={"character_id": "char_alice"},
    )

    # Enqueue 2
    r1 = await http_client.post(
        f"/api/scene-multiplayer/{scene_id}/turn/enqueue",
        params={"actor_id": "p1"},
        json={"verb": "look"},
    )
    assert r1.status_code == 200
    assert r1.json()["queue_size"] == 1

    r2 = await http_client.post(
        f"/api/scene-multiplayer/{scene_id}/turn/enqueue",
        params={"actor_id": "p1"},
        json={"verb": "move", "target": "door"},
    )
    assert r2.json()["queue_size"] == 2

    # Queue size endpoint
    r = await http_client.get(f"/api/scene-multiplayer/{scene_id}/turn/queue-size")
    assert r.json()["queue_size"] == 2

    # Process first ticket
    r = await http_client.post(f"/api/scene-multiplayer/{scene_id}/turn/process")
    assert r.status_code == 200
    body = r.json()
    assert body["ticket"] is not None
    assert body["ticket"]["action"]["verb"] == "look"
    assert body["queue_size"] == 1

    # Process second ticket
    r = await http_client.post(f"/api/scene-multiplayer/{scene_id}/turn/process")
    body = r.json()
    assert body["ticket"]["action"]["verb"] == "move"
    assert body["queue_size"] == 0

    # Process on empty queue returns ticket=None
    r = await http_client.post(f"/api/scene-multiplayer/{scene_id}/turn/process")
    assert r.json()["ticket"] is None


@pytest.mark.asyncio
async def test_http_isolation_check_endpoint(
    http_client: AsyncClient,
) -> None:
    """The ``/isolation/check`` endpoint mirrors the guard's rules."""
    scene_id = "http_isolation_scene_1"

    await http_client.post(f"/api/scene-multiplayer/{scene_id}/create")
    await http_client.post(
        f"/api/scene-multiplayer/{scene_id}/player/p_alice/join",
        params={"character_id": "char_alice"},
    )
    await http_client.post(
        f"/api/scene-multiplayer/{scene_id}/player/p_bob/join",
        params={"character_id": "char_bob"},
    )
    await http_client.post(
        f"/api/scene-multiplayer/{scene_id}/npcs",
    )  # no-op; just to keep the pattern explicit

    # Own char → allowed
    r = await http_client.get(
        f"/api/scene-multiplayer/{scene_id}/isolation/check",
        params={
            "requester_id": "p_alice",
            "target_character_id": "char_alice",
            "op": "read",
        },
    )
    assert r.status_code == 200
    assert r.json()["allowed"] is True

    # Other char → denied
    r = await http_client.get(
        f"/api/scene-multiplayer/{scene_id}/isolation/check",
        params={
            "requester_id": "p_alice",
            "target_character_id": "char_bob",
            "op": "read",
        },
    )
    assert r.json()["allowed"] is False

    # Unknown scene → denied
    r = await http_client.get(
        "/api/scene-multiplayer/ghost_scene/isolation/check",
        params={
            "requester_id": "p_alice",
            "target_character_id": "char_alice",
        },
    )
    assert r.json()["allowed"] is False

    # Bad op → 400
    r = await http_client.get(
        f"/api/scene-multiplayer/{scene_id}/isolation/check",
        params={
            "requester_id": "p_alice",
            "target_character_id": "char_alice",
            "op": "delete",  # not a valid op
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_http_health_endpoint_returns_dict(
    http_client: AsyncClient,
) -> None:
    """``/api/scene-multiplayer/health`` returns the registry aggregate."""
    r = await http_client.get("/api/scene-multiplayer/health")
    assert r.status_code == 200
    body = r.json()
    assert "scene_count" in body
    assert "by_scene" in body
    assert isinstance(body["scene_count"], int)


@pytest.mark.asyncio
async def test_http_join_full_scene_returns_409(
    http_client: AsyncClient,
) -> None:
    """5th player join → 409 (scene full)."""
    scene_id = "http_full_scene_1"
    await http_client.post(f"/api/scene-multiplayer/{scene_id}/create")
    for i in range(4):
        r = await http_client.post(
            f"/api/scene-multiplayer/{scene_id}/player/p{i+1}/join",
            params={"character_id": f"char_{i+1}"},
        )
        assert r.status_code == 200, r.text
    # 5th rejected
    r = await http_client.post(
        f"/api/scene-multiplayer/{scene_id}/player/p5/join",
        params={"character_id": "char_5"},
    )
    assert r.status_code == 409
    assert "join_rejected" in r.json()["detail"]


@pytest.mark.asyncio
async def test_http_unknown_scene_returns_404(
    http_client: AsyncClient,
) -> None:
    """Endpoints on a never-created scene → 404."""
    r = await http_client.get("/api/scene-multiplayer/never_created_scene/players")
    assert r.status_code == 404
    r = await http_client.get("/api/scene-multiplayer/never_created_scene/npcs")
    assert r.status_code == 404
    r = await http_client.get("/api/scene-multiplayer/never_created_scene/turn/queue-size")
    assert r.status_code == 404
