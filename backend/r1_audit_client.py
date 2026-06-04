"""
R1-14B Real Audit Client
=========================
Connects to a real DeepSeek R1-Distill-Qwen-14B model running on
LM Studio at 127.0.0.1:1234 (or any OpenAI-compatible endpoint).

This is the production path for the audit-hook skill \u2014 not a mock.
When LM Studio is not running, falls back to raising a clear error
(no silent M3 substitution).

Usage:
    from backend.r1_audit_client import R1AuditClient, audit_memory_palace

    client = R1AuditClient()
    report = await client.audit(
        target_files=[
            "backend/memory_palace.py",
            "backend/tests/test_memory_palace.py",
            "docs/WAVE2_MEMORY_PALACE.md",
        ],
        concerns=[
            "God Agent I/O bottleneck (500+ NPCs)",
            "Dynamic decay calculation cost (e^-rt at query time)",
            "Cross-DB sync / 2PC / compensation (Phase B LanceDB)",
        ],
    )
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)

# ============================================
# Configuration
# ============================================

DEFAULT_BASE_URL = os.getenv("R1_BASE_URL", "http://127.0.0.1:1234/v1")
DEFAULT_MODEL = os.getenv("R1_MODEL", "deepseek-r1-distill-qwen-14b")
DEFAULT_TIMEOUT = 300  # R1 reasoning is slow; 5 min budget


# ============================================
# Client
# ============================================


class R1AuditClient:
    """Real R1-14B client. No silent fallback to other models."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._http = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._http.aclose()

    async def verify_endpoint(self) -> Dict[str, Any]:
        """
        Pre-flight: confirm the endpoint has the R1 model loaded.
        Raises RuntimeError if not available.
        """
        try:
            r = await self._http.get(f"{self.base_url}/models")
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"Cannot reach LM Studio at {self.base_url}: {e}\n"
                f"  -> Start LM Studio and load deepseek-r1-distill-qwen-14b"
            ) from e
        if r.status_code != 200:
            raise RuntimeError(f"LM Studio returned HTTP {r.status_code}")
        data = r.json()
        models = [m.get("id", "?") for m in data.get("data", [])]
        if self.model not in models:
            raise RuntimeError(
                f"Model '{self.model}' not loaded in LM Studio.\n"
                f"  Available: {models}\n"
                f"  -> Load the model in LM Studio UI before running audit"
            )
        return {"base_url": self.base_url, "model": self.model, "available_models": models}

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.1,
        max_tokens: int = 8000,
    ) -> str:
        """
        Send a chat completion request to R1.
        Returns the assistant's content (after reasoning_content is consumed).
        """
        r = await self._http.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
                # R1 specific: ask it to think before responding
                # LM Studio passes this through to the model
            },
        )
        if r.status_code != 200:
            raise RuntimeError(
                f"R1 returned HTTP {r.status_code}: {r.text[:200]}"
            )
        data = r.json()
        choice = data["choices"][0]
        return choice["message"]["content"]

    async def audit(
        self,
        target_files: List[str],
        concerns: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Send an architecture audit request to real R1.

        Returns:
            {
                "verdict": "PASS" | "CONDITIONAL" | "FAIL" | "BLOCK",
                "findings": [
                    {"severity": "CRITICAL/HIGH/MEDIUM/LOW/INFO",
                     "concern": str, "issue": str, "evidence": str,
                     "recommendation": str},
                    ...
                ],
                "raw_response": str,  # R1's full output
            }
        """
        # Verify endpoint first
        endpoint_info = await self.verify_endpoint()
        logger.info(f"R1 audit starting; model={endpoint_info['model']}")

        # Build the user message
        file_contents = {}
        for f in target_files:
            p = Path(f)
            if p.exists():
                # Read at most 100 lines to fit R1's 6K context (5 files)
                content = p.read_text(encoding="utf-8", errors="replace")
                lines = content.split("\n")
                if len(lines) > 100:
                    content = "\n".join(lines[:100]) + f"\n... [truncated; {len(lines)-100} more lines]"
                file_contents[f] = content
            else:
                file_contents[f] = f"[FILE NOT FOUND]"

        # Use a SHORT system prompt to preserve context for the actual content
        system_prompt = "You are R1, an architecture auditor. Output JSON in the user's required format."

        user_message = (
            "Perform an architecture audit of the following files. "
            "These are real production code paths.\n\n"
            f"## Target Files\n\n"
            + "\n\n".join(
                f"### `{f}`\n```\n{file_contents[f]}\n```"
                for f in target_files
            )
            + f"\n\n## Specific Concerns to Audit\n\n"
            + "\n".join(f"{i+1}. {c}" for i, c in enumerate(concerns))
            + (f"\n\n## Additional Context\n\n```json\n{json.dumps(context, indent=2, ensure_ascii=False)}\n```"
               if context else "")
            + "\n\n## Required Report Format\n\n"
            "Respond with a JSON block (no other text outside the JSON):\n"
            "```json\n"
            "{\n"
            '  "verdict": "PASS" | "CONDITIONAL" | "FAIL" | "BLOCK",\n'
            '  "reasoning_summary": "<one-paragraph reasoning>",\n'
            '  "findings": [\n'
            '    {\n'
            '      "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO",\n'
            '      "concern_index": <int, 1-based>,\n'
            '      "issue": "<short title>",\n'
            '      "evidence": "<file:line citation, must be verifiable>",\n'
            '      "recommendation": "<concrete fix>"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n"
        )

        raw = await self.chat(system_prompt, user_message)

        # Try to extract JSON block
        verdict = "UNKNOWN"
        findings: List[Dict[str, Any]] = []
        json_start = raw.find("{")
        json_end = raw.rfind("}")
        if json_start >= 0 and json_end > json_start:
            try:
                parsed = json.loads(raw[json_start:json_end+1])
                verdict = parsed.get("verdict", "UNKNOWN")
                findings = parsed.get("findings", [])
            except json.JSONDecodeError:
                logger.warning("R1 response is not valid JSON; using raw text only")

        return {
            "endpoint": endpoint_info,
            "verdict": verdict,
            "findings": findings,
            "raw_response": raw,
        }


# ============================================
# Convenience function
# ============================================


async def audit_memory_palace(repo_root: str = ".") -> Dict[str, Any]:
    """
    Run a real R1 audit on the Memory Palace code.
    """
    client = R1AuditClient()
    try:
        await client.verify_endpoint()
        result = await client.audit(
            target_files=[
                f"{repo_root}/backend/memory_palace.py",
                f"{repo_root}/backend/tests/test_memory_palace.py",
                f"{repo_root}/docs/WAVE2_MEMORY_PALACE.md",
            ],
            concerns=[
                "God Agent I/O bottleneck (500+ NPCs doing daily ETL via apply_decay / consolidate_memories / transfer_memories)",
                "Dynamic decay calculation cost (exp(-r*t) at query time vs batch-only)",
                "Cross-DB sync / 2PC / compensation (Phase B will add LanceDB alongside SQLite)",
                "Post-audit-fix regression: are the 3 HIGH fixes (N+1, atomicity, exponential formula) actually correctly implemented?",
            ],
        )
        return result
    finally:
        await client.close()


async def audit_full_wave2(repo_root: str = ".") -> Dict[str, Any]:
    """
    Real R1 audit covering all Wave 2 deliverables:
    - memory_palace.py (post R1 fixes)
    - soul_transfer.py (new)
    - r1_audit_client.py (audit infrastructure)
    - test_soul_transfer.py (22 new tests)

    Verifies:
    1. Soul Transfer atomicity (no partial-state risk)
    2. Degradation engine is anti-predictable
    3. Memory Palace R1 fixes are correctly implemented
    4. R1 audit client itself meets production quality bar
    """
    client = R1AuditClient()
    try:
        await client.verify_endpoint()
        result = await client.audit(
            target_files=[
                f"{repo_root}/backend/memory_palace.py",
                f"{repo_root}/backend/soul_transfer.py",
                f"{repo_root}/backend/r1_audit_client.py",
                f"{repo_root}/backend/tests/test_soul_transfer.py",
            ],
            concerns=[
                "Soul Transfer atomicity: does transfer_memories' all-or-nothing semantics actually prevent partial-state corruption under concurrent God Agent ETL?",
                "Anti-predictability: is the random [0.6, 0.9] degradation factor truly non-deterministic, or could a player game it by repeat-transfer?",
                "Memory Palace R1-fix correctness: are the 3 HIGH issues (N+1 connection, transfer transaction, exponential decay formula) ACTUALLY fixed in the current code? Or are they merely renamed/shuffled?",
                "Test coverage: do the 22 new Soul Transfer tests genuinely exercise the contract, or are they tautological?",
                "Audit infrastructure quality: is R1AuditClient production-grade (timeout, error handling, retry on transient failures)?",
                "Cross-cutting: any new architectural debt that Phase B/C will inherit?",
            ],
            context={
                "version": "Wave 2 v0.2.0",
                "shipped_commits": [
                    "fc1384b (R1 audit fixes for memory_palace)",
                    "8cd60b9 (real R1 audit client)",
                    "3deea0c (Soul Transfer implementation)",
                ],
                "test_count": 94,
            },
        )
        return result
    finally:
        await client.close()


async def audit_full_wave2_stack(repo_root: str = ".") -> Dict[str, Any]:
    """
    Real R1 audit covering the entire Wave 2 stack:
    - turn_system.py (Async Turn System)
    - etl_service.py (God Agent ETL with outbox pattern)
    - soul_transfer.py (already audited in round 2, re-verify)
    - memory_palace.py (already audited, re-verify post-Core3)
    - r1_audit_client.py (audit infra self-quality)

    Verifies:
    1. Async Turn System's DB row lock is actually concurrent-safe
       under God Agent ETL concurrency
    2. Outbox pattern correctly mitigates R1 finding 1 (cross-file
       atomicity) for the ETL use case
    3. No new architectural debt introduced by Core #3
    4. Cross-module integration: turn_system + etl_service +
       memory_palace + soul_transfer work together coherently
    5. Performance: do the new patterns scale to 500+ characters?
    """
    client = R1AuditClient()
    try:
        await client.verify_endpoint()
        result = await client.audit(
            target_files=[
                f"{repo_root}/backend/turn_system.py",
                f"{repo_root}/backend/etl_service.py",
                f"{repo_root}/backend/soul_transfer.py",
                f"{repo_root}/backend/memory_palace.py",
                f"{repo_root}/backend/r1_audit_client.py",
            ],
            concerns=[
                "Async Turn System: does the DB row lock (UPDATE ... WHERE turn_id = subquery RETURNING) actually prevent two concurrent advance_turn() from claiming the same turn? Or is there a race window between SELECT and UPDATE?",
                "God Agent ETL outbox pattern: does the etl_outbox approach actually mitigate R1 finding 1 (cross-file atomicity) for the apply_decay case, or is it a partial fix that hides deeper issues?",
                "Cross-module integration: when turn_system.complete_turn triggers memory_palace.apply_round + soul_transfer, do the three modules agree on transaction boundaries? Or does each module hold its own SQLite connection without coordination?",
                "Performance: at 500+ characters, do the per-character SQLite operations (turns + memory_palace + soul_transfer) scale linearly, or do they create connection-pool exhaustion / lock contention?",
                "Audit infrastructure: is the R1AuditClient itself production-grade (timeout handling, retry on transient errors, JSON parsing safety)?",
                "New architectural debt: did Core #3 introduce any patterns that Phase B/C will need to refactor?",
            ],
            context={
                "version": "Wave 2 v0.3.0",
                "shipped_commits": [
                    "fc1384b (R1 audit fixes for memory_palace)",
                    "8cd60b9 (real R1 audit client)",
                    "3deea0c (Soul Transfer implementation)",
                    "f0eb45a (concurrency tests for Soul Transfer)",
                    "5328c92 (Async Turn System + God Agent ETL)",
                ],
                "test_count": 117,
                "previous_r1_audits": [
                    "Round 1 (M3 mock, on memory_palace Phase A): CONDITIONAL, 8 findings",
                    "Round 2 (real R1, on Wave 2 v0.2.0): FAIL, 6 findings, 1 fixed (#4)",
                ],
            },
        )
        return result
    finally:
        await client.close()
