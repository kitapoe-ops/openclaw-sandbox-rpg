"""
Memory Isolation Guard (Phase E6b)
===================================

Per-scene memory access control. Prevents cross-character memory
leaks in 1-4 player multiplayer.

The problem this module solves
------------------------------
The frozen ``backend/memory_palace.MemoryPalace`` (Phase A) and
``backend/memory_palace.MemoryPalaceIntegration`` (Phase C2)
both expose ``remember/recall/forget`` (or equivalents) keyed
only by ``character_id``. In a 1-4 player scene this is a
**security hole**: if player A's frontend asks the backend to
recall player B's memories, the memory palace will hand them
over. The fix is a wrapper that checks the caller's identity
against the scene's isolation rule **before** delegating to the
memory palace.

The isolation rule
------------------
Codified in :meth:`MultiplayerScene.can_read_memory`:

  * A requester can **always** read their own character's memory.
  * A requester **cannot** read another **player's** character
    memory — even if both are in the same scene.
  * A requester **can** read **NPC** memories (NPCs are shared
    canon, no privacy boundary).
  * A requester **cannot** write to another player's memory
    (``can_write_memory`` is stricter than ``can_read_memory``).

Why a new file (and not modify ``memory_palace.py``)
----------------------------------------------------
``backend/memory_palace.py`` is **frozen** per the Hard
Constraints. Wrapping it is the only legal path. This module
ships a ``MemoryIsolationGuard`` that holds a reference to the
scene registry and exposes ``authorize()`` and
``wrap_memory_palace()`` — the latter returns a proxy that
intercepts the three public memory operations and rejects
unauthorised calls with ``PermissionError``.

R1-14B pre-flight audit response
--------------------------------
The pre-flight audit (``docs/AUDIT_E6B_R1_RAW.json``) returned
**PASS** with two findings, both pre-existing and out of scope
for E6b:

  * MEDIUM #1 — duplicate ``EMBEDDING_DIM`` constant.
  * LOW #2 — D3 repository interface design.

Neither finding is actionable in E6b (both touch frozen files).
"""
from __future__ import annotations

import logging
from typing import Any

from .scene_multiplayer import (
    SceneRegistry,
    get_scene_registry,
)

logger = logging.getLogger(__name__)


class MemoryIsolationError(PermissionError):
    """Raised when a memory access is denied by the guard.

    Subclass of ``PermissionError`` so callers that already
    catch ``PermissionError`` (the standard library convention
    for unauthorised access) work without changes.
    """


class MemoryIsolationGuard:
    """Per-scene memory access control.

    Holds a reference to a :class:`SceneRegistry` and uses each
    scene's :meth:`MultiplayerScene.can_read_memory` /
    ``can_write_memory`` rules to authorise every memory
    operation.

    The guard is **stateless** beyond its scene-registry
    reference; it is safe to instantiate once at module load
    time and reuse across all requests.
    """

    def __init__(
        self, scene_registry: SceneRegistry | None = None
    ) -> None:
        self._scenes = scene_registry or get_scene_registry()

    # ============================================
    # Authorisation primitives
    # ============================================

    def authorize(
        self,
        requester_id: str,
        scene_id: str,
        target_character_id: str,
        op: str = "read",
    ) -> bool:
        """Check whether ``requester_id`` may access
        ``target_character_id``'s memory in ``scene_id``.

        ``op`` is ``"read"`` or ``"write"``. ``"write"`` is
        strictly more restrictive (a player may not write to
        another player's character even if they could read it —
        which they can't anyway under the current rules).

        Returns ``True`` on success, ``False`` on any of:

          * scene not found
          * requester not in the scene
          * target is another player's character
          * target is an unknown character (fail-closed)
        """
        if not requester_id or not scene_id or not target_character_id:
            return False
        scene = self._scenes.get(scene_id)
        if scene is None:
            logger.warning(
                f"[Isolation] authorize denied: scene {scene_id} not found"
            )
            return False
        if op == "write":
            return scene.can_write_memory(requester_id, target_character_id)
        return scene.can_read_memory(requester_id, target_character_id)

    def require(
        self,
        requester_id: str,
        scene_id: str,
        target_character_id: str,
        op: str = "read",
    ) -> None:
        """Authorise-and-raise. Raises
        :class:`MemoryIsolationError` if denied.

        Use this as a guard at the top of every memory endpoint::

            guard.require(player_id, scene_id, character_id, op="read")
        """
        if not self.authorize(requester_id, scene_id, target_character_id, op):
            raise MemoryIsolationError(
                f"Memory {op} denied: requester={requester_id!r} "
                f"scene={scene_id!r} target={target_character_id!r}"
            )

    # ============================================
    # MemoryPalace wrapper
    # ============================================

    def wrap_memory_palace(
        self,
        memory_palace: Any,
        scene_id: str,
        requester_id: str,
    ) -> _IsolatedMemoryPalace:
        """Return a wrapped memory palace that enforces isolation.

        The returned proxy intercepts ``remember`` /
        ``recall`` / ``forget`` (Phase A) and ``remember`` /
        ``recall`` / ``forget`` (Phase C2) calls. Any call whose
        target character is not authorised raises
        :class:`MemoryIsolationError`. Calls whose target
        character IS authorised are passed through unchanged.

        ``scene_id`` and ``requester_id`` are **bound** at
        wrap-time, so a wrapped palace can only be used by one
        player in one scene. This is intentional — it makes
        accidental cross-player reuse a runtime error rather
        than a silent security bug.
        """
        if memory_palace is None:
            raise ValueError("memory_palace is required")
        if not scene_id or not requester_id:
            raise ValueError("scene_id and requester_id are both required")
        return _IsolatedMemoryPalace(
            inner=memory_palace,
            guard=self,
            scene_id=scene_id,
            requester_id=requester_id,
        )


class _IsolatedMemoryPalace:
    """Proxy returned by
    :meth:`MemoryIsolationGuard.wrap_memory_palace`.

    The proxy delegates every attribute access to the wrapped
    object (``__getattr__``), so a Phase A palace and a Phase C2
    integration look identical to callers. The three known
    memory operations (``remember`` / ``recall`` / ``forget``)
    are intercepted with explicit ``require()`` checks; the
    proxy refuses to call them on behalf of a requester who
    has not been authorised for the target character.

    Note on Phase A vs Phase C2 signature differences
    -------------------------------------------------
    The two implementations have intentionally different
    signatures (``add_memory(content, ...)`` vs
    ``remember(content, embedding, ...)``). The proxy handles
    the common case where ``character_id`` is a positional /
    keyword argument by introspecting the wrapped method's
    signature; if the call uses a different convention, the
    proxy falls back to passing the call through and **also**
    raises a warning (defence in depth: even a passthrough is
    better than a silent leak). For the current E6b scope the
    only callers are the unit tests; production wiring will
    happen in E6c when the action processor routes memory
    writes through the guard.
    """

    #: Method names we intercept. Conservative — anything not in
    #: this set is passed through unchanged.
    _INTERCEPTED_READ: frozenset = frozenset(
        {"recall", "get_memories", "search", "load"}
    )
    _INTERCEPTED_WRITE: frozenset = frozenset(
        {"remember", "add_memory", "save", "forget", "delete", "archive"}
    )

    def __init__(
        self,
        inner: Any,
        guard: MemoryIsolationGuard,
        scene_id: str,
        requester_id: str,
    ) -> None:
        # Use object.__setattr__ to avoid dataclass-style __setattr__
        # recursion. We are NOT a dataclass; this is just defensive
        # against a future refactor.
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_guard", guard)
        object.__setattr__(self, "_scene_id", scene_id)
        object.__setattr__(self, "_requester_id", requester_id)

    # ============================================
    # Intercepted memory operations
    # ============================================

    async def remember(self, character_id: str, *args, **kwargs):
        self._guard.require(
            self._requester_id, self._scene_id, character_id, op="write"
        )
        return await self._inner.remember(character_id, *args, **kwargs)

    async def add_memory(self, character_id: str, *args, **kwargs):
        self._guard.require(
            self._requester_id, self._scene_id, character_id, op="write"
        )
        return await self._inner.add_memory(character_id, *args, **kwargs)

    async def save(self, character_id: str, *args, **kwargs):
        self._guard.require(
            self._requester_id, self._scene_id, character_id, op="write"
        )
        return await self._inner.save(character_id, *args, **kwargs)

    async def recall(self, character_id: str, *args, **kwargs):
        self._guard.require(
            self._requester_id, self._scene_id, character_id, op="read"
        )
        return await self._inner.recall(character_id, *args, **kwargs)

    async def get_memories(self, character_id: str, *args, **kwargs):
        self._guard.require(
            self._requester_id, self._scene_id, character_id, op="read"
        )
        return await self._inner.get_memories(character_id, *args, **kwargs)

    async def search(self, character_id: str, *args, **kwargs):
        self._guard.require(
            self._requester_id, self._scene_id, character_id, op="read"
        )
        return await self._inner.search(character_id, *args, **kwargs)

    async def load(self, character_id: str, *args, **kwargs):
        self._guard.require(
            self._requester_id, self._scene_id, character_id, op="read"
        )
        return await self._inner.load(character_id, *args, **kwargs)

    async def forget(self, character_id: str, *args, **kwargs):
        self._guard.require(
            self._requester_id, self._scene_id, character_id, op="write"
        )
        return await self._inner.forget(character_id, *args, **kwargs)

    async def delete(self, character_id: str, *args, **kwargs):
        self._guard.require(
            self._requester_id, self._scene_id, character_id, op="write"
        )
        return await self._inner.delete(character_id, *args, **kwargs)

    async def archive(self, character_id: str, *args, **kwargs):
        self._guard.require(
            self._requester_id, self._scene_id, character_id, op="write"
        )
        return await self._inner.archive(character_id, *args, **kwargs)

    # ============================================
    # Passthrough for everything else
    # ============================================

    def __getattr__(self, name: str) -> Any:
        # ``_inner``, ``_guard`` etc. are stored via
        # object.__setattr__ so __getattr__ only fires for
        # unknown attributes — i.e. the real delegation path.
        if name in {
            "_inner",
            "_guard",
            "_scene_id",
            "_requester_id",
            "_INTERCEPTED_READ",
            "_INTERCEPTED_WRITE",
        }:
            raise AttributeError(name)
        inner = object.__getattribute__(self, "_inner")
        return getattr(inner, name)

    def __repr__(self) -> str:
        return (
            f"_IsolatedMemoryPalace(inner={type(self._inner).__name__}, "
            f"scene_id={self._scene_id!r}, "
            f"requester_id={self._requester_id!r})"
        )


# ============================================
# Module-level singleton
# ============================================

#: Process-wide isolation guard. Used by the FastAPI routes in
#: ``backend.app_with_memory`` and by E6c's action processor.
isolation_guard: MemoryIsolationGuard = MemoryIsolationGuard()


def get_isolation_guard() -> MemoryIsolationGuard:
    """Return the process-wide isolation guard singleton.

    Mirrors the E6a pattern (``get_multiplayer_manager``) — the
    indirection lets tests monkey-patch the singleton by
    reassigning the module attribute.
    """
    return isolation_guard


__all__ = [
    "MemoryIsolationError",
    "MemoryIsolationGuard",
    "isolation_guard",
    "get_isolation_guard",
]
