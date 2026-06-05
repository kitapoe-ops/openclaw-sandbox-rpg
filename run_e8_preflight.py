"""Pre-flight E8 audit: run a real R1 audit on the proposed async queue design."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# E8 is pre-implementation, so the design is a draft embedded in the brief.
# We audit the proposed interface + the surrounding context (turn_system,
# r1_audit_client, the E8 brief itself).
from backend.r1_audit_client import R1AuditClient


async def main() -> int:
    # The proposed interface is in docs/PHASE_E8_SUMMARY.md (will be created
    # at the end), and in the brief. We construct an in-line sketch for R1.
    design_doc = """# Phase E8 — Async Audit Queue (PROPOSED INTERFACE, DRAFT)

The framework supports 1-4 players + 100 NPCs per scene. When all 104
actors submit actions in a turn cycle, calling R1-14B synchronously per
action would take 5-10s × 104 = 8-17 minutes per turn — unacceptable.

This task builds an async audit queue that lets the game continue while
R1 audits in the background.

## Proposed interface

```python
import asyncio
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum
import time

class AuditVerdict(str, Enum):
    PENDING = "pending"
    PASS = "pass"
    CONDITIONAL = "conditional"
    FAIL = "fail"
    ERROR = "error"
    TIMEOUT = "timeout"

@dataclass
class AuditRequest:
    request_id: str
    target_files: List[str]
    concerns: List[str]
    context: Optional[Dict[str, Any]] = None
    submitted_at: float = field(default_factory=time.time)
    deadline: Optional[float] = None  # unix timestamp

@dataclass
class AuditResult:
    request_id: str
    verdict: AuditVerdict
    findings: List[Dict[str, Any]] = field(default_factory=list)
    raw_response: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    error: Optional[str] = None

class AsyncAuditQueue:
    def __init__(self, r1_client, worker_count=2, max_queue_size=200,
                 request_timeout=600.0): ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def submit(self, request: AuditRequest) -> str: ...
    async def get_result(self, request_id, timeout=None) -> AuditResult: ...
    def get_status(self, request_id) -> AuditVerdict: ...
    def health(self) -> dict: ...
```

## Design choices (embedded in the brief)
- worker_count = 2 (R1 on a single GPU handles ~1 concurrent; 2 is headroom)
- max_queue_size = 200 (worst case 100 NPC + 4 player + buffer)
- backpressure: asyncio.Queue(maxsize=200) blocks put() when full
- request_timeout = 600s
- result storage: in-memory dict keyed by request_id
- singleton factory `get_audit_queue()`

## Integration point
- The audit-hook skill (in api/action.py) will call `get_audit_queue().submit(req)`
  and return a request_id immediately (HTTP 202 Accepted).
- Caller can poll `get_status(req_id)` or await `get_result(req_id)`.
- The action endpoint is NOT modified by E8 — it remains frozen.
"""

    # Save the prompt for transparency.
    Path("docs/AUDIT_E8_PROMPT.md").write_text(design_doc, encoding="utf-8")

    client = R1AuditClient()
    try:
        await client.verify_endpoint()
        result = await client.audit(
            target_files=[
                "backend/turn_system.py",
                "backend/r1_audit_client.py",
                "backend/api/action.py",
            ],
            concerns=[
                "Async queue sizing: 200 queue depth + 2 workers against worst-case 104 actors/turn — does the math work? Specifically: at 5-10s per R1 audit, 2 workers drain ~12-24 req/min, but 104 reqs arrive in a burst. Will backpressure (block on put()) cause request submission to hang, defeating the 'game continues while audit runs' goal?",
                "Backpressure strategy: asyncio.Queue(maxsize=200) blocks put() when full. Is blocking the right policy for a player-facing game loop? Or should the queue (a) drop oldest with a warning, (b) raise immediately so caller can decide, (c) return a sentinel 'queue full, audit skipped' verdict. Audit for the user-facing UX risk of each.",
                "Timeout policy: 600s (10 min) per request. R1 reasoning can exceed this on complex code. Should timeout be per-request (current) or per-batch (audit_phase_d3_repository took 90s for 4 files)? Also: when a request times out, should the worker mark it TIMEOUT and move on, or retry with a longer deadline? Audit for the failure-mode behaviour.",
                "Result lifecycle: in-memory dict, no persistence. If the FastAPI process restarts mid-game, all in-flight audit results are lost. Is this acceptable for the game UX (player just retries) or a correctness issue (audit was load-bearing for the action outcome)? Should results be written to SQLite/Postgres for durability, or is in-memory fine for v0?",
                "Worker pool concurrency: 2 workers call R1-14B concurrently. R1 on a single GPU with ~9GB VRAM is already at the edge of single-request throughput. Will 2 concurrent requests thrash GPU memory / serialize at the model level? Or does LM Studio's batching make 2 reqs ≈ 1.5× the latency of 1? Audit for the realistic worker_count for a single-GPU R1-14B.",
                "Integration with frozen action.py: the audit-hook skill in api/action.py is READ-ONLY. Where does the queue get instantiated (per-request, per-app, per-process)? If singleton via get_audit_queue(), who owns its lifecycle (start/stop on FastAPI startup/shutdown)? Audit for the cleanest wiring given the freeze constraint.",
            ],
            context={
                "phase": "E8",
                "purpose": "Pre-implementation design audit — the interface above has not been written yet",
                "constraint": "api/action.py is FROZEN — integration must be done by callers, not by editing action.py",
                "frozen_files": [
                    "backend/character.py", "backend/scene.py", "backend/action.py",
                    "backend/world.py", "backend/vector_store.py", "backend/scheduler.py",
                    "backend/persistence_pg.py", "backend/state_machine.py",
                    "backend/memory_palace.py", "backend/memory_palace_integration.py",
                    "backend/memory_palace_integration_endpoint.py",
                    "backend/memory_repository.py", "backend/llm_client.py",
                    "backend/api/action_processor.py",
                    "backend/r1_audit_client.py",
                    "backend/app_with_memory.py", "backend/demo_integration.py",
                    "backend/main.py", "backend/uvicorn_launcher.py",
                ],
                "previous_r1_audits": [
                    "Round 1-3 on memory_palace / turn_system / etl_service / soul_transfer: PASS, no audit-queue findings yet",
                    "Phase D6 LLM client audit: FAIL (6 findings) — all addressed; recommended retry + 429 handling + cache. E8 queue complements this by adding the async backpressure layer.",
                ],
            },
        )

        # Save raw + parsed
        Path("docs/AUDIT_E8_RAW.txt").write_text(result.get("raw_response", ""), encoding="utf-8")
        # Convert verdict to uppercase for consistency with the existing audit files
        out = dict(result)
        out["verdict"] = (out.get("verdict") or "UNKNOWN").upper()
        Path("docs/AUDIT_E8_RESULT.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"E8 pre-flight audit verdict: {out['verdict']}")
        print(f"Findings: {len(out.get('findings', []))}")
        for i, f in enumerate(out.get("findings", []), 1):
            sev = f.get("severity", "?")
            issue = f.get("issue", "?")
            print(f"  {i}. [{sev}] {issue}")
        return 0
    except Exception as e:
        print(f"Pre-flight audit failed: {e}")
        # Save the prompt for offline use
        Path("docs/AUDIT_E8_PROMPT.md").write_text(design_doc, encoding="utf-8")
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
