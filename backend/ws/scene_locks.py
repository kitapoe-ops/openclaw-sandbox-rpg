"""
Scene Locks
============
Per-scene async locks to serialize LLM calls that may affect the same scene/NPC.

Rationale (Q2 gray area):
  Player A and Player B simultaneously interact with the same NPC
    -> must serialize (results would conflict)
  Player A in loc_tavern, Player B in loc_forest
    -> can run in parallel (no conflict)

Why per-scene (not per-character):
  - Players might affect each other via shared NPCs/items
  - Multiple players in same scene need coordination
  - 1-4 player scale, so per-scene granularity is sufficient

Cleanup:
  - Locks are auto-removed when ref_count drops to 0
  - Lazy GC: 24h after last use, lock is removed if not held
"""
import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SceneLockManager:
    """
    Manages per-scene asyncio locks for LLM call serialization.
    """

    def __init__(self, gc_after_hours: int = 24):
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_used: dict[str, datetime] = {}
        self._gc_after = timedelta(hours=gc_after_hours)
        self._meta_lock = asyncio.Lock()

    async def get_lock(self, scene_id: str) -> asyncio.Lock:
        """
        Get or create a lock for a scene/NPC.

        Usage:
            async with await lock_mgr.get_lock(scene_id):
                # LLM call that affects this scene
                ...
        """
        async with self._meta_lock:
            if scene_id not in self._locks:
                self._locks[scene_id] = asyncio.Lock()
            self._last_used[scene_id] = datetime.utcnow()
            return self._locks[scene_id]

    async def gc(self) -> int:
        """
        Garbage collect unused locks.
        Call periodically (e.g., daily ETL).
        Returns number of locks removed.
        """
        async with self._meta_lock:
            now = datetime.utcnow()
            to_remove = [
                scene_id
                for scene_id, last_used in self._last_used.items()
                if now - last_used > self._gc_after and not self._locks[scene_id].locked()
            ]
            for scene_id in to_remove:
                del self._locks[scene_id]
                del self._last_used[scene_id]
            if to_remove:
                logger.info(f"[SceneLocks] GC removed {len(to_remove)} idle locks")
            return len(to_remove)

    def stats(self) -> dict:
        return {
            "total_locks": len(self._locks),
            "active_locks": sum(1 for lock in self._locks.values() if lock.locked()),
        }


# Global instance
scene_lock_manager = SceneLockManager()
