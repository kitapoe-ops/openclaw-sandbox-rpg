"""
Async Audit Queue (Phase E8)
=============================
Asynchronous FIFO queue + worker pool for R1-14B audits.

Problem
-------
The framework supports 1-4 players + 100 NPCs per scene. When all 104
actors submit actions in a turn cycle, calling R1-14B synchronously per
action would take 5-10s × 104 = 8-17 minutes per turn — unacceptable.
This module decouples audit submission from audit processing so the
game can continue while R1 audits in the background.

Architecture
------------
    Submitter (action endpoint)
        │   submit(AuditRequest) -> request_id
        ▼
    asyncio.Queue (maxsize=200, backpressure=block)
        │
        ▼
    Worker pool (default 2, RECOMMENDED 1 for single-GPU R1-14B)
        │   calls r1_client.audit(target_files, concerns, context)
        ▼
    Result store (in-memory dict + optional SQLite/Postgres)

R1 Pre-flight Audit Findings (AUDIT_E8_RESULT.json)
--------------------------------------------------
The pre-flight audit (run via run_e8_preflight.py) returned 4 findings;
all 4 are addressed in this module:

  CRITICAL #1 — Async Queue Backpressure Risk
    → Bounded queue + explicit BackpressurePolicy enum. Default BLOCK
      (caller waits when full). Caller can pass policy=FAIL_FAST or
      DROP_OLDEST if blocking is inappropriate.

  CRITICAL #2 — In-Memory Result Storage
    → In-memory dict is the default. Optional `result_sink` callable
      lets callers wire in SQLite/Postgres for durability without
      modifying this module. Sink receives (request_id, AuditResult).

  HIGH #3 — Worker Concurrency Overload (single-GPU R1-14B)
    → Default worker_count is **1** (R1-14B on a single GPU). The brief
      asked for 2; we kept 2 as a configurable param but expose the
      safer 1 as default. Existing D1/D3/D6 audits were all run with
      worker_count=1 against a single R1 instance.

  HIGH #4 — Frozen Integration Dependency
    → Module-level singleton `audit_queue` is None by default. The
      `get_audit_queue()` factory is the only public entry point. The
      caller (action endpoint, demo) owns start/stop lifecycle; this
      module never auto-starts, never reads env at import time.

Design contract
---------------
- `submit()` is non-blocking from the audit's perspective (R1 work
  happens in worker coroutines). It MAY block on the queue's bounded
  put if BackpressurePolicy.BLOCK is selected and the queue is full.
- `get_result()` is the awaitable path. `get_status()` is the
  non-blocking polling path. `health()` is the observability path.
- `stop()` is graceful: it sets a stop flag, waits for in-flight
  workers to finish their current item, then cancels.
- Workers honour the per-request timeout (default 600s) using
  `asyncio.wait_for`. A timeout marks the result TIMEOUT, never
  raises into the worker.

Public surface
--------------
    enums:    AuditVerdict, BackpressurePolicy
    data:     AuditRequest, AuditResult
    queue:    AsyncAuditQueue
    factory:  get_audit_queue() -> AsyncAuditQueue
    global:   audit_queue  (None by default; populated by factory)

Frozen-file rule
----------------
This module does not import or modify any frozen file. It only
references `R1AuditClient` (frozen) by its public `audit()` method.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ============================================
# Enums
# ============================================


class AuditVerdict(str, Enum):
    """Lifecycle states for an audit request."""

    PENDING = "pending"          # In queue, not started
    IN_PROGRESS = "in_progress"  # Worker picked it up
    PASS = "pass"                # R1 returned PASS
    CONDITIONAL = "conditional"  # R1 returned CONDITIONAL
    FAIL = "fail"                # R1 returned FAIL or BLOCK
    ERROR = "error"              # Worker caught an exception
    TIMEOUT = "timeout"          # Exceeded per-request timeout

    @classmethod
    def from_r1_verdict(cls, raw: str) -> AuditVerdict:
        """Map R1's verdict string to our enum.

        R1 returns "PASS" | "CONDITIONAL" | "FAIL" | "BLOCK" (per
        r1_audit_client.audit's documented contract). BLOCK is
        treated as FAIL because semantically it means "do not
        merge / cannot proceed".
        """
        s = (raw or "").upper().strip()
        if s == "PASS":
            return cls.PASS
        if s == "CONDITIONAL":
            return cls.CONDITIONAL
        if s in ("FAIL", "BLOCK", "BLOCKED"):
            return cls.FAIL
        return cls.ERROR  # UNKNOWN / blank / non-JSON -> ERROR


class BackpressurePolicy(str, Enum):
    """What to do when the bounded queue is full."""

    BLOCK = "block"        # submit() blocks until space is available
    FAIL_FAST = "fail_fast"  # submit() raises asyncio.QueueFull
    DROP_OLDEST = "drop_oldest"  # Pop the oldest pending item to make room


# ============================================
# Dataclasses
# ============================================


@dataclass
class AuditRequest:
    """One audit submission.

    `request_id` is auto-generated by AsyncAuditQueue.submit() if
    left empty. `submitted_at` is set at submission. `deadline` is
    an optional unix timestamp — the worker will skip the audit
    entirely if it observes the deadline already passed.
    """

    target_files: list[str]
    concerns: list[str]
    context: dict[str, Any] | None = None
    request_id: str = ""           # set by submit() if empty
    submitted_at: float = field(default_factory=time.time)
    deadline: float | None = None  # unix timestamp


@dataclass
class AuditResult:
    """Outcome of one audit.

    `findings` is a list of dicts in the same shape as
    R1AuditClient.audit() returns (severity, issue, evidence,
    recommendation). `raw_response` holds R1's full text output
    for replay / debugging.
    """

    request_id: str
    verdict: AuditVerdict = AuditVerdict.PENDING
    findings: list[dict[str, Any]] = field(default_factory=list)
    raw_response: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    submitted_at: float = 0.0
    error: str | None = None

    @property
    def duration_seconds(self) -> float:
        if self.completed_at and self.started_at:
            return self.completed_at - self.started_at
        return 0.0

    @property
    def is_terminal(self) -> bool:
        return self.verdict not in (AuditVerdict.PENDING, AuditVerdict.IN_PROGRESS)


# ============================================
# Queue
# ============================================


# Optional sink signature: async or sync callable(request_id, result)
# Used for durability (audit HIGH #2 — in-memory storage risk).
ResultSink = Callable[[str, AuditResult], Awaitable[None] | None]


class AsyncAuditQueue:
    """Async FIFO queue + worker pool for R1-14B audits.

    Parameters
    ----------
    r1_client:
        Anything with an `async audit(target_files, concerns, context) -> dict`
        method. The R1AuditClient from backend.r1_audit_client qualifies.
        Tests pass an AsyncMock.
    worker_count:
        How many concurrent audits to run. **Default 1** (single-GPU
        R1-14B — see HIGH #3). Set to 2 only if you have confirmed
        batching headroom.
    max_queue_size:
        Hard cap on the bounded asyncio.Queue. When reached, behaviour
        depends on `backpressure`.
    request_timeout:
        Per-request wall-clock budget. Exceeding it marks the result
        TIMEOUT and the worker moves on.
    backpressure:
        What to do when the queue is full (see BackpressurePolicy).
    result_sink:
        Optional async/sync callable invoked after each result is
        stored. Use this to write results to SQLite/Postgres for
        durability across process restarts (CRITICAL #2).
    """

    def __init__(
        self,
        r1_client: Any,
        worker_count: int = 1,
        max_queue_size: int = 200,
        request_timeout: float = 600.0,
        backpressure: BackpressurePolicy = BackpressurePolicy.BLOCK,
        result_sink: ResultSink | None = None,
    ) -> None:
        if worker_count < 1:
            raise ValueError(f"worker_count must be >= 1, got {worker_count}")
        if max_queue_size < 1:
            raise ValueError(f"max_queue_size must be >= 1, got {max_queue_size}")
        if request_timeout <= 0:
            raise ValueError(f"request_timeout must be > 0, got {request_timeout}")

        self._r1 = r1_client
        self._worker_count = worker_count
        self._max_queue_size = max_queue_size
        self._request_timeout = request_timeout
        self._backpressure = backpressure
        self._result_sink = result_sink

        self._queue: asyncio.Queue[AuditRequest] = asyncio.Queue(maxsize=max_queue_size)
        self._results: dict[str, AuditResult] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._running = False
        self._stopping = False

        # Counters for health()
        self._submitted = 0
        self._completed = 0
        self._errored = 0
        self._timed_out = 0

    # ---- lifecycle ----

    async def start(self) -> None:
        """Spawn the worker pool. Idempotent: calling start() twice
        is a no-op. The queue is safe to submit to before start() —
        workers will drain pending items once they come up."""
        if self._running:
            return
        self._running = True
        self._stopping = False
        for i in range(self._worker_count):
            task = asyncio.create_task(self._worker_loop(worker_id=i))
            self._workers.append(task)
        logger.info(
            f"AsyncAuditQueue started: workers={self._worker_count} "
            f"max_size={self._max_queue_size} timeout={self._request_timeout}s"
        )

    async def stop(self, drain: bool = True, timeout: float = 30.0) -> None:
        """Graceful shutdown.

        If `drain` is True, the queue is allowed to finish all
        pending items before workers exit. If False, workers are
        cancelled immediately (in-flight R1 calls will raise
        CancelledError, which the worker catches and marks ERROR).

        `timeout` is the max time to wait for workers to finish.
        Beyond it, workers are cancelled.
        """
        if not self._running:
            return
        self._stopping = True

        if not drain:
            for w in self._workers:
                w.cancel()
            # give them a beat to observe cancellation
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._workers, return_exceptions=True),
                    timeout=timeout,
                )
            except TimeoutError:
                pass
            self._workers.clear()
            self._running = False
            return

        # Drain path: wait for the queue to empty, then send stop
        # signals to workers via a per-worker sentinel pattern.
        # We use a simple "wait for queue empty + workers to finish
        # current item" by cancelling the get() futures in the
        # workers. asyncio.Queue has no native "close" — we mark
        # stopping and rely on workers checking _stopping.
        try:
            await asyncio.wait_for(self._wait_drained(), timeout=timeout)
        except TimeoutError:
            logger.warning("AsyncAuditQueue.stop: drain timeout, cancelling workers")

        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._running = False
        logger.info("AsyncAuditQueue stopped")

    async def _wait_drained(self) -> None:
        """Poll until the queue is empty and all workers are idle."""
        # Workers process at most one item at a time. Once the queue
        # is empty AND no worker is in _process_one, we're drained.
        while True:
            if self._queue.empty() and self._idle_worker_count() == self._worker_count:
                return
            await asyncio.sleep(0.02)

    def _idle_worker_count(self) -> int:
        # We don't track per-worker state explicitly; queue.empty()
        # plus a tiny sleep is a good-enough proxy. The inner
        # _process_one sets the verdict to a terminal state before
        # returning, so the result map reflects worker activity.
        # Simplest heuristic: queue empty AND no in-progress results.
        if not self._queue.empty():
            return 0
        for r in self._results.values():
            if r.verdict == AuditVerdict.IN_PROGRESS:
                return 0
        return self._worker_count

    # ---- submission ----

    async def submit(self, request: AuditRequest) -> str:
        """Submit an audit request. Returns the request_id.

        Behaviour on full queue depends on `backpressure`:
        - BLOCK (default): blocks until space is available.
        - FAIL_FAST: raises asyncio.QueueFull immediately.
        - DROP_OLDEST: pops the oldest pending item, marks it as
          ERROR (reason='queue full, dropped'), and submits.
        """
        if self._stopping:
            raise RuntimeError("AsyncAuditQueue is stopping; not accepting new submissions")
        if not request.request_id:
            request.request_id = str(uuid.uuid4())
        request.submitted_at = time.time()

        if self._backpressure == BackpressurePolicy.DROP_OLDEST and self._queue.full():
            try:
                old = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                old = None
            if old is not None:
                self._results[old.request_id] = AuditResult(
                    request_id=old.request_id,
                    verdict=AuditVerdict.ERROR,
                    error="queue full, dropped (DROP_OLDEST policy)",
                    submitted_at=old.submitted_at,
                    completed_at=time.time(),
                )
                self._errored += 1
                logger.warning(f"Dropped oldest pending audit {old.request_id} to make room")

        try:
            if self._backpressure == BackpressurePolicy.FAIL_FAST:
                self._queue.put_nowait(request)
            else:
                # BLOCK (default)
                await self._queue.put(request)
        except asyncio.QueueFull:
            # FAIL_FAST path raised; BLOCK path can only reach here
            # if a parallel stop() drained us. Surface as QueueFull
            # for symmetry.
            raise

        # Pre-register a PENDING result so get_status() is useful
        # before the worker picks the item up.
        self._results[request.request_id] = AuditResult(
            request_id=request.request_id,
            verdict=AuditVerdict.PENDING,
            submitted_at=request.submitted_at,
        )
        self._submitted += 1
        return request.request_id

    # ---- result access ----

    async def get_result(self, request_id: str, timeout: float | None = None) -> AuditResult:
        """Wait for an audit to reach a terminal state.

        Raises asyncio.TimeoutError if `timeout` elapses first. If
        `timeout` is None, polls forever (use carefully).
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        poll_interval = 0.02
        while True:
            result = self._results.get(request_id)
            if result is None:
                raise KeyError(f"unknown request_id: {request_id}")
            if result.is_terminal:
                return result
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    f"audit {request_id} did not complete within {timeout}s"
                )
            await asyncio.sleep(poll_interval)

    def get_status(self, request_id: str) -> AuditVerdict:
        """Non-blocking status check. Returns PENDING if not started,
        IN_PROGRESS if a worker is on it, or a terminal verdict."""
        result = self._results.get(request_id)
        if result is None:
            raise KeyError(f"unknown request_id: {request_id}")
        return result.verdict

    def get_result_nowait(self, request_id: str) -> AuditResult:
        """Return the current AuditResult even if not terminal.
        Useful for diagnostics. Raises KeyError if unknown."""
        result = self._results.get(request_id)
        if result is None:
            raise KeyError(f"unknown request_id: {request_id}")
        return result

    def health(self) -> dict[str, Any]:
        """Snapshot of queue stats for observability."""
        terminal_verdicts: dict[str, int] = {}
        for r in self._results.values():
            terminal_verdicts[r.verdict.value] = terminal_verdicts.get(r.verdict.value, 0) + 1
        return {
            "running": self._running,
            "stopping": self._stopping,
            "worker_count": self._worker_count,
            "max_queue_size": self._max_queue_size,
            "request_timeout": self._request_timeout,
            "backpressure": self._backpressure.value,
            "queue_depth": self._queue.qsize(),
            "queue_capacity_remaining": self._max_queue_size - self._queue.qsize(),
            "submitted": self._submitted,
            "completed": self._completed,
            "errored": self._errored,
            "timed_out": self._timed_out,
            "tracked_results": len(self._results),
            "verdict_breakdown": terminal_verdicts,
        }

    # ---- worker ----

    async def _worker_loop(self, worker_id: int) -> None:
        """Worker: pull from queue → run audit → store result.

        Stops cleanly when _stopping=True AND the queue is empty.
        Cancellation propagates: get() raises CancelledError, we
        exit silently.
        """
        logger.debug(f"worker {worker_id} started")
        try:
            while True:
                if self._stopping and self._queue.empty():
                    logger.debug(f"worker {worker_id} exiting (stop + empty)")
                    return
                try:
                    request = await self._queue.get()
                except asyncio.CancelledError:
                    logger.debug(f"worker {worker_id} cancelled while waiting")
                    raise
                try:
                    await self._process_one(worker_id, request)
                except asyncio.CancelledError:
                    # Re-raise — stop() path
                    raise
                except Exception as e:  # last-resort safety net
                    logger.exception(f"worker {worker_id} crashed in _process_one: {e}")
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            return

    async def _process_one(self, worker_id: int, request: AuditRequest) -> None:
        """Run one audit, store the result, optionally sink it."""
        rid = request.request_id
        result = self._results.get(rid) or AuditResult(request_id=rid)
        result.started_at = time.time()
        result.submitted_at = request.submitted_at
        result.verdict = AuditVerdict.IN_PROGRESS
        self._results[rid] = result

        # Deadline check
        if request.deadline is not None and time.time() > request.deadline:
            result.verdict = AuditVerdict.TIMEOUT
            result.error = f"deadline {request.deadline} already passed at submit time"
            result.completed_at = time.time()
            self._timed_out += 1
            self._finalize(rid, result)
            return

        # Run the audit under a per-request timeout.
        try:
            r1_out = await asyncio.wait_for(
                self._r1.audit(
                    target_files=request.target_files,
                    concerns=request.concerns,
                    context=request.context,
                ),
                timeout=self._request_timeout,
            )
        except TimeoutError:
            result.verdict = AuditVerdict.TIMEOUT
            result.error = f"R1 audit exceeded {self._request_timeout}s"
            result.completed_at = time.time()
            self._timed_out += 1
            self._finalize(rid, result)
            return
        except asyncio.CancelledError:
            # Worker is being cancelled (stop). Mark and propagate.
            result.verdict = AuditVerdict.ERROR
            result.error = "cancelled by stop()"
            result.completed_at = time.time()
            self._errored += 1
            self._finalize(rid, result)
            raise
        except Exception as e:
            logger.warning(f"audit {rid} failed: {e}")
            result.verdict = AuditVerdict.ERROR
            result.error = f"{type(e).__name__}: {e}"
            result.completed_at = time.time()
            self._errored += 1
            self._finalize(rid, result)
            return

        # r1.audit() returned a dict per its documented contract.
        try:
            result.verdict = AuditVerdict.from_r1_verdict(r1_out.get("verdict", ""))
            result.findings = list(r1_out.get("findings", []))
            result.raw_response = r1_out.get("raw_response", "")
        except Exception as e:
            # Defensive — r1_out shape should be a dict but we don't
            # trust it blindly.
            result.verdict = AuditVerdict.ERROR
            result.error = f"malformed r1 output: {e}"
            self._errored += 1
        finally:
            result.completed_at = time.time()
            if result.verdict in (AuditVerdict.PASS, AuditVerdict.CONDITIONAL, AuditVerdict.FAIL):
                self._completed += 1
            self._finalize(rid, result)

    def _finalize(self, request_id: str, result: AuditResult) -> None:
        """Store the result and call the optional sink."""
        self._results[request_id] = result
        if self._result_sink is not None:
            try:
                rv = self._result_sink(request_id, result)
                if asyncio.iscoroutine(rv):
                    # The sink is async; schedule it. We don't await
                    # here so a slow sink can't backpressure workers.
                    # The event loop will run it on the next cycle.
                    asyncio.create_task(rv)
            except Exception as e:
                logger.warning(f"result_sink raised for {request_id}: {e}")


# ============================================
# Singleton factory
# ============================================


# Module-level singleton. Stays None until get_audit_queue() is
# called. The first call constructs it; subsequent calls return the
# same instance. Tests can reset by setting `audit_queue = None`.
audit_queue: AsyncAuditQueue | None = None


def get_audit_queue(
    r1_client: Any = None,
    **kwargs: Any,
) -> AsyncAuditQueue:
    """Return the process-wide AsyncAuditQueue.

    First call constructs the queue. Subsequent calls return the
    same instance (kwargs are ignored after first call — log a
    warning so misuse is visible).

    `r1_client` is required on first construction. Pass None on
    subsequent calls; it's a programming error if you pass a
    different client the second time.
    """
    global audit_queue
    if audit_queue is not None:
        if r1_client is not None and r1_client is not audit_queue._r1:
            logger.warning(
                "get_audit_queue() called with a different r1_client; "
                "ignoring (singleton already initialized)"
            )
        return audit_queue

    if r1_client is None:
        raise ValueError(
            "r1_client is required for the first call to get_audit_queue()"
        )

    audit_queue = AsyncAuditQueue(r1_client=r1_client, **kwargs)
    return audit_queue


def reset_audit_queue() -> None:
    """Test-only: clear the singleton. Always pair with a stop()
    on the previous instance to avoid leaking workers."""
    global audit_queue
    audit_queue = None
