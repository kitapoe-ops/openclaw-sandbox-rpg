# Phase E8 — Async Audit Queue (PROPOSED INTERFACE, DRAFT)

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
