"""
Action Queue
=============
In-memory queue for player actions awaiting LLM processing.

Decouples WS Handler from LLM Worker.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class QueuedAction:
    """A player action awaiting LLM processing."""
    task_id: str
    character_id: str
    payload: Dict[str, Any]
    submitted_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "pending"  # pending | processing | completed | failed
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ActionQueue:
    """
    In-memory queue for player actions.

    For production with multiple workers, replace with Redis Queue (RQ) or Celery.
    For single-process MVP, asyncio.Queue is sufficient.

    Design:
    - Multiple characters can be in the queue simultaneously
    - Per-character serialization (one task per character at a time)
    - Status tracking via task_id
    """

    def __init__(self, max_per_character: int = 5):
        # Global queue (FIFO across all characters)
        self._queue: asyncio.Queue = asyncio.Queue()
        # Track tasks by task_id
        self._tasks: Dict[str, QueuedAction] = {}
        # Per-character locks to prevent concurrent LLM calls for same character
        self._character_locks: Dict[str, asyncio.Lock] = {}
        # Max queue size per character (prevent flooding)
        self._max_per_character = max_per_character
        self._lock = asyncio.Lock()

    async def enqueue(self, action: QueuedAction) -> bool:
        """
        Enqueue an action. Returns False if character's queue is full.
        """
        async with self._lock:
            # Check per-character queue size
            char_queue_size = sum(
                1 for t in self._tasks.values()
                if t.character_id == action.character_id
                and t.status in ("pending", "processing")
            )
            if char_queue_size >= self._max_per_character:
                logger.warning(
                    f"[Queue] Character {action.character_id} queue full "
                    f"({char_queue_size}/{self._max_per_character})"
                )
                return False

            self._tasks[action.task_id] = action
            await self._queue.put(action)
            logger.info(
                f"[Queue] Enqueued {action.task_id} for {action.character_id}. "
                f"Queue size: {self._queue.qsize()}"
            )
            return True

    async def dequeue(self) -> Optional[QueuedAction]:
        """Dequeue next action. Blocks if queue is empty."""
        try:
            action = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            action.status = "processing"
            action.started_at = datetime.utcnow()
            return action
        except asyncio.TimeoutError:
            return None

    async def mark_completed(self, task_id: str, result: Dict[str, Any]) -> None:
        """Mark task as completed with result."""
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].status = "completed"
                self._tasks[task_id].result = result
                self._tasks[task_id].completed_at = datetime.utcnow()
                logger.info(f"[Queue] Task {task_id} completed")

    async def mark_failed(self, task_id: str, error: str) -> None:
        """Mark task as failed."""
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].status = "failed"
                self._tasks[task_id].error = error
                self._tasks[task_id].completed_at = datetime.utcnow()
                logger.error(f"[Queue] Task {task_id} failed: {error}")

    async def get_task(self, task_id: str) -> Optional[QueuedAction]:
        """Get task by ID (for status queries)."""
        async with self._lock:
            return self._tasks.get(task_id)

    async def get_character_locks(self) -> Dict[str, asyncio.Lock]:
        """Get or create per-character locks (for serialization)."""
        async with self._lock:
            return self._character_locks

    def stats(self) -> dict:
        """Queue statistics."""
        return {
            "queue_size": self._queue.qsize(),
            "total_tasks": len(self._tasks),
            "by_status": {
                "pending": sum(1 for t in self._tasks.values() if t.status == "pending"),
                "processing": sum(1 for t in self._tasks.values() if t.status == "processing"),
                "completed": sum(1 for t in self._tasks.values() if t.status == "completed"),
                "failed": sum(1 for t in self._tasks.values() if t.status == "failed"),
            },
        }


# Global queue instance
action_queue = ActionQueue()
