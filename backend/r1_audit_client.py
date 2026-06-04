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
                # Read at most 150 lines to fit R1's 6K context
                content = p.read_text(encoding="utf-8", errors="replace")
                lines = content.split("\n")
                if len(lines) > 150:
                    content = "\n".join(lines[:150]) + f"\n... [truncated; {len(lines)-150} more lines]"
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
