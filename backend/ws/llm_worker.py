"""
LLM Worker (Background Task)
=============================
Processes actions from the ActionQueue in background.
Calls Scene Agent + Sub Agent, persists results to DB, broadcasts to clients.

CRITICAL: This is a separate asyncio task that runs independently of WS lifecycle.
Even if client disconnects, this worker continues processing.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

from .action_queue import ActionQueue, QueuedAction
from .connection_manager import ConnectionRegistry

logger = logging.getLogger(__name__)


class LLMWorker:
    """
    Background worker that processes actions from the queue.

    Lifecycle:
    - Start: asyncio.create_task(self._run())
    - Run: continuously dequeue and process
    - Each task: call LLM (5-15s), persist to DB, broadcast result

    Failure handling:
    - LLM timeout: mark task as failed, broadcast error
    - DB write failure: retry with exponential backoff
    - WS broadcast failure: save to pending updates (handled by registry)
    """

    def __init__(
        self,
        action_queue: ActionQueue,
        registry: ConnectionRegistry,
        llm_client=None,  # Will be injected
        db_session=None,  # Will be injected
    ):
        self.action_queue = action_queue
        self.registry = registry
        self.llm_client = llm_client
        self.db_session = db_session
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._character_locks: dict = {}

    async def start(self) -> None:
        """Start the background worker."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("[LLMWorker] Started")

    async def stop(self) -> None:
        """Stop the worker gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[LLMWorker] Stopped")

    async def _run(self) -> None:
        """Main worker loop."""
        logger.info("[LLMWorker] Entering main loop")
        while self._running:
            try:
                action = await self.action_queue.dequeue()
                if action is None:
                    # Queue empty, continue polling
                    await asyncio.sleep(0.1)
                    continue

                await self._process_action(action)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"[LLMWorker] Unexpected error: {e}")
                await asyncio.sleep(1)  # Avoid tight error loop

    async def _process_action(self, action: QueuedAction) -> None:
        """
        Process a single action.

        Steps:
        1. Get per-character lock (serialize LLM calls for same character)
        2. Call Scene Agent (LLM, 5-15s)
        3. Call Sub Agent (state calculation)
        4. Persist scene_output to DB
        5. Update character state in DB
        6. Broadcast scene_update to active connections
        7. Mark task as completed
        """
        char_id = action.character_id
        task_id = action.task_id
        logger.info(f"[LLMWorker] Processing task {task_id} for {char_id}")

        # Get or create per-character lock
        if char_id not in self._character_locks:
            self._character_locks[char_id] = asyncio.Lock()

        async with self._character_locks[char_id]:
            try:
                # 1. Send "processing" status update
                await self.registry.broadcast(char_id, {
                    "type": "task_status",
                    "task_id": task_id,
                    "status": "processing",
                    "message": "Generating scene...",
                })

                # 2. Call LLM (TODO: implement actual LLM call)
                scene_output = await self._call_llm(action)

                # 3. Persist to DB (TODO: implement)
                # await self._persist_scene(action, scene_output)

                # 4. Broadcast scene_update
                await self.registry.broadcast(char_id, {
                    "type": "scene_update",
                    "task_id": task_id,
                    "round": scene_output.get("round"),
                    "narrative": scene_output.get("narrative"),
                    "choices": scene_output.get("choices"),
                    "state_changes": scene_output.get("state_changes"),
                    "minor_event": scene_output.get("minor_event"),
                })

                # 5. Mark completed
                await self.action_queue.mark_completed(task_id, scene_output)
                logger.info(f"[LLMWorker] Task {task_id} completed and broadcast")

            except Exception as e:
                logger.exception(f"[LLMWorker] Task {task_id} failed: {e}")
                await self.action_queue.mark_failed(task_id, str(e))
                # Notify client of failure
                await self.registry.broadcast(char_id, {
                    "type": "task_status",
                    "task_id": task_id,
                    "status": "failed",
                    "error": str(e),
                }, save_if_disconnected=True)

    async def _call_llm(self, action: QueuedAction) -> dict:
        """
        Call Scene Agent + Sub Agent to generate scene output.

        TODO: Implement actual LLM integration.
        Reference: docs/PROMPTS/scene_agent_prompt.md
        """
        # Placeholder: returns a dummy scene
        logger.info(f"[LLMWorker] LLM call for task {action.task_id} (placeholder)")
        await asyncio.sleep(2)  # Simulate LLM latency

        return {
            "round": 1,
            "narrative": "你睇到一個場景...（TODO: 真實 LLM 生成）",
            "choices": [
                {
                    "id": "opt_01",
                    "lore_source": "item:dummy",
                    "text": "【行動】繼續探索",
                    "intent_category": "environment",
                    "attitude_options": [
                        {"dimension": "caution", "level": "careful"}
                    ]
                }
            ],
            "state_changes": {},
            "minor_event": None,
        }


# Global worker instance
llm_worker: Optional[LLMWorker] = None


def init_worker(
    action_queue: ActionQueue,
    registry: ConnectionRegistry,
    llm_client=None,
    db_session=None,
) -> LLMWorker:
    """Initialize the global LLM worker."""
    global llm_worker
    llm_worker = LLMWorker(action_queue, registry, llm_client, db_session)
    return llm_worker
