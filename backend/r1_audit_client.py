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
from typing import Any

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

    async def verify_endpoint(self) -> dict[str, Any]:
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
            raise RuntimeError(f"R1 returned HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        choice = data["choices"][0]
        return choice["message"]["content"]

    async def audit(
        self,
        target_files: list[str],
        concerns: list[str],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
                    content = (
                        "\n".join(lines[:100]) + f"\n... [truncated; {len(lines)-100} more lines]"
                    )
                file_contents[f] = content
            else:
                file_contents[f] = "[FILE NOT FOUND]"

        # Use a SHORT system prompt to preserve context for the actual content
        system_prompt = (
            "You are R1, an architecture auditor. Output JSON in the user's required format."
        )

        user_message = (
            "Perform an architecture audit of the following files. "
            "These are real production code paths.\n\n"
            "## Target Files\n\n"
            + "\n\n".join(f"### `{f}`\n```\n{file_contents[f]}\n```" for f in target_files)
            + "\n\n## Specific Concerns to Audit\n\n"
            + "\n".join(f"{i+1}. {c}" for i, c in enumerate(concerns))
            + (
                f"\n\n## Additional Context\n\n```json\n{json.dumps(context, indent=2, ensure_ascii=False)}\n```"
                if context
                else ""
            )
            + "\n\n## Required Report Format\n\n"
            "Respond with a JSON block (no other text outside the JSON):\n"
            "```json\n"
            "{\n"
            '  "verdict": "PASS" | "CONDITIONAL" | "FAIL" | "BLOCK",\n'
            '  "reasoning_summary": "<one-paragraph reasoning>",\n'
            '  "findings": [\n'
            "    {\n"
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
        findings: list[dict[str, Any]] = []
        json_start = raw.find("{")
        json_end = raw.rfind("}")
        if json_start >= 0 and json_end > json_start:
            try:
                parsed = json.loads(raw[json_start : json_end + 1])
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


async def audit_memory_palace(repo_root: str = ".") -> dict[str, Any]:
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


async def audit_full_wave2(repo_root: str = ".") -> dict[str, Any]:
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


async def audit_full_wave2_stack(repo_root: str = ".") -> dict[str, Any]:
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


async def audit_phase_d1_merge(repo_root: str = ".") -> dict[str, Any]:
    """
    Real R1 audit for Phase D1 — merge the two memory_palace modules.

    Phase D1 scope: decide between (a) keep both modules (caller picks) or
    (b) consolidate into one module with two classes. Migrates 30 existing
    test_memory_palace.py tests.

    Verifies:
    1. Test migration risk (SQLite-only coupling / monkey-patches)
    2. API surface overlap (remember/recall/forget signatures)
    3. Class name preservation / single-class-with-backend alternative
    4. Backward compatibility of import paths post-merge
    """
    client = R1AuditClient()
    try:
        await client.verify_endpoint()
        result = await client.audit(
            target_files=[
                f"{repo_root}/backend/memory_palace.py",
                f"{repo_root}/backend/memory_palace_integration.py",
                f"{repo_root}/backend/tests/test_memory_palace.py",
                f"{repo_root}/backend/tests/test_memory_palace_integration.py",
            ],
            concerns=[
                "Test migration risk: will the 30 existing test_memory_palace.py tests survive a module merge? Are any tightly coupled to SQLite-only behavior of the original MemoryPalace class (e.g. monkey-patching the sqlite3 connection, hard-coded path patterns like tmp_path / 'memory_test.db', or direct module-level imports of internal helpers like MemoryType/MemorySource enums)?",
                "API surface overlap: both classes expose remember/recall/forget. Do they have incompatible signatures that would break callers? Specifically check remember(content=...) keyword form on the Phase A class vs remember(character_id, content, embedding, memory_type, salience, metadata) positional form on MemoryPalaceIntegration. Will auto-converted callers silently mis-call the merged class?",
                "Class name preservation vs. third option: the brief says 'merge into one module with two classes' OR 'keep both'. Is there a third option (single class with backend parameter — e.g. MemoryPalace(backend='sqlite'|'postgres_vector')) that the brief missed, and which option produces the cleanest call sites going forward?",
                "Backward compatibility: will the existing 30-test test_memory_palace.py still pass after the merge? Specifically the import path 'from backend.memory_palace import MemoryPalace' — does it need to be re-exported from the merged module to avoid clobbering 30 shipped tests? Also test_memory_palace_integration.py imports — same question.",
            ],
            context={
                "phase": "D1",
                "shipped_commits": [
                    "204749c (Phase B + C shipped; memory_palace.py 841L + memory_palace_integration.py 552L coexist)",
                    "10898ae (Phase C docs shipped)",
                ],
                "test_count": 161,
                "files_in_scope": {
                    "memory_palace.py": "841L, 30 tests, SQLite-only Phase A",
                    "memory_palace_integration.py": "552L, 12 unit + 6 endpoint tests, PG + Vector composition",
                },
                "previous_r1_audits": [
                    "Round 1 (M3 mock, on memory_palace Phase A): CONDITIONAL, 8 findings",
                    "Round 2 (real R1, on Wave 2 v0.2.0): FAIL, 6 findings, 1 fixed (#4)",
                    "Round 3 (real R1, on Wave 2 v0.3.0 stack): PASS, 4 findings (informational)",
                ],
            },
        )
        return result
    finally:
        await client.close()


async def audit_phase_d3_repository(repo_root: str = ".") -> dict[str, Any]:
    """
    Real R1 audit for Phase D3 — Memory Palace Phase B + C (Repository pattern
    + real embedding model integration).

    Phase D3 scope: abstract MemoryRepository interface (so caller can swap
    SQLite/Postgres without changing business logic) + replace 384-dim stub
    embeddings with sentence-transformers/all-MiniLM-L6-v2.

    Verifies:
    1. Repository interface design (which methods to abstract)
    2. Real embedding model loading pattern (sync/lazy/async)
    3. Cache layer placement (decorator vs internal)
    4. Embedding compute cost at 500+ characters with daily ETL
    """
    client = R1AuditClient()
    try:
        await client.verify_endpoint()
        result = await client.audit(
            target_files=[
                f"{repo_root}/backend/memory_palace_integration.py",
                f"{repo_root}/backend/persistence_pg.py",
                f"{repo_root}/backend/vector_store.py",
                f"{repo_root}/docs/WAVE2_MEMORY_PALACE.md",
            ],
            concerns=[
                "Repository interface design: what methods must MemoryRepository abstract? Current MemoryPalaceIntegration has 6 public methods (remember/recall/forget/count/health/close). Does the repository need to expose all 6, or only a subset (e.g. just CRUD: save/load/delete/find, with recall being a higher-level service that composes a VectorSearchPort + PersistencePort)? Audit for the minimum surface that still lets callers swap backends without code changes.",
                "Real embedding integration: sentence-transformers/all-MiniLM-L6-v2 is ~90MB on disk, ~200MB RAM at load. Where does the model load? Synchronous at import (blocks app startup, fails fast on missing model)? Lazy on first encode() call (deferred cost, can fail mid-request)? Async via to_thread / run_in_executor (off-loads event loop, cleanest for FastAPI)? Recommend the cleanest pattern and call out the failure mode of each.",
                "Cache layer placement: Phase C will add a Redis cache for hot memories. Should the cache wrap the repository (decorator pattern — MemoryRepository → CachedRepository → PostgresRepository) or be internal to the integration class (MemoryPalaceIntegration owns both repository and cache, repository stays pure)? Audit for the cleanest separation that lets tests run without Redis.",
                "Real embedding cost: at 500+ characters with daily ETL, how often is embed() called? Audit for whether a model-side cache (e.g. content-hash keyed in-process LRU + Redis shared cache) is needed before going to sentence-transformers every time. Estimate: 500 chars × 1 remember/turn × 10 turns/session × 50 sessions/day = 250k encodes/day; at ~5ms/encode on CPU = 21 min/day pure CPU. Is the cache worth the complexity?",
            ],
            context={
                "phase": "D3",
                "design_source": "docs/WAVE2_MEMORY_PALACE.md §5 + §7",
                "shipped_commits": [
                    "204749c (Phase B: vector_store.py 471L, persistence_pg.py 343L)",
                    "204749c (Phase C2: memory_palace_integration.py 552L, 12 unit tests)",
                ],
                "test_count": 161,
                "candidate_backends": {
                    "persistence": ["PostgresPersistence (Phase B3)", "aiosqlite fallback (tests)"],
                    "vector": ["LanceDB (Phase B1)", "pure-Python fallback (tests)"],
                },
                "previous_r1_audits": [
                    "Round 1: CONDITIONAL, memory_palace SQLite scaling risk",
                    "Round 3: PASS, 5-module stack — no findings blocking repository extraction",
                ],
            },
        )
        return result
    finally:
        await client.close()


async def audit_phase_d5_pi5_deploy(repo_root: str = ".") -> dict[str, Any]:
    """
    Real R1 audit for Phase D5 — Docker deploy to Pi5 (8GB RAM, no GPU).

    Phase D5 scope: add backend Dockerfile, deploy docker-compose stack to
    kitahim.ddns.net (Pi5 already has Caddy reverse proxy + Cloudflare Tunnel).

    Verifies:
    1. Pi5 RAM budget under R1-14B absence (8GB shared with OS, FastAPI,
       Postgres, APScheduler, embedding model)
    2. Embedding model load cost on ARM
    3. Postgres vs SQLite tradeoff for a single-node Pi5
    4. Reverse proxy topology (Caddy + Cloudflare Tunnel) — WebSocket,
       large payload, reconnect
    """
    client = R1AuditClient()
    try:
        await client.verify_endpoint()
        result = await client.audit(
            target_files=[
                f"{repo_root}/docker-compose.yml",
                f"{repo_root}/backend/requirements.txt",
                f"{repo_root}/backend/main.py",
                f"{repo_root}/backend/r1_audit_client.py",
            ],
            concerns=[
                "Pi5 RAM budget (8GB total, ~6GB available after OS): without GPU, deepseek-r1-distill-qwen-14b (R1-14B, ~9GB VRAM) cannot run on Pi5 at all. Audit: should the audit client fail gracefully on Pi5 (skip audit, allow LLM output to pass, log a warning) or should the entire action pipeline be disabled (no LLM narrator means no gameplay)? Recommend the safest default for a production deploy with no local LLM.",
                "Embedding model load: sentence-transformers/all-MiniLM-L6-v2 uses ~200MB RAM resident plus ~50MB for ONNX runtime. Will it fit alongside FastAPI (~150MB) + Postgres (~300MB with shared_buffers) + APScheduler (negligible) on 6GB available? Total steady-state: ~700MB. Headroom looks OK, but a cold-start spike during model load could OOM if the OS is mid-swap. Audit for the load-time risk and whether model pre-load at startup is wise.",
                "Postgres vs SQLite on Pi5: the default in-memory + aiosqlite path works on any host with zero extra processes. Does deploying Postgres (via docker-compose) on a single-node Pi5 add value (FK enforcement, concurrent writers, pgvector for future), or is it overhead (extra ~300MB RAM, separate container to manage, slower on SD card I/O)? Audit for a 1-node production deploy.",
                "Reverse proxy topology (Caddy + Cloudflare Tunnel): is there any framework-side concern with the existing deployment topology? Specifically: (a) WebSocket reconnect logic when the tunnel drops — does the frontend re-establish within the 100s Cloudflare idle timeout? (b) large memory payload size — recall returns up to k=50 results × 384-dim = 19,200 floats per response (~150KB JSON), fine but at k=50 with metadata could approach 500KB; audit whether streaming / pagination is needed. (c) Memory Palace writes to ./data/*.db on a SD card — does the docker-compose volume mount survive container restarts?",
            ],
            context={
                "phase": "D5",
                "target_host": "Pi5 (8GB RAM, no GPU, ARM64, kitahim.ddns.net)",
                "existing_infra": {
                    "reverse_proxy": "Caddy (port 443) → backend port 8000",
                    "tunnel": "Cloudflare Tunnel (no port forwarding needed)",
                    "auth": "basic_auth on /rota/ (not on /api/)",
                },
                "shipped_artifacts": [
                    "docker-compose.yml (postgres + backend + optional frontend)",
                    "deploy/docker/backend.Dockerfile (referenced but not yet created)",
                    "backend/requirements.txt (heavy: sqlalchemy, asyncpg, lancedb, redis, etc.)",
                ],
                "test_count": 161,
                "previous_r1_audits": [
                    "Round 1-3: all on desktop x86_64 with GPU — no Pi5 findings yet",
                ],
            },
        )
        return result
    finally:
        await client.close()


async def audit_phase_d6_llm_client(repo_root: str = ".") -> dict[str, Any]:
    """
    Real R1 audit for Phase D6 — replace mock LLM client with real
    MiniMax-M3 cloud (1M context, thinking mode on).

    Phase D6 scope: productionize backend/llm_client.py — add retry logic,
    rate-limit handling, optional response caching. Audit for clean
    separation of concerns.

    Verifies:
    1. Retry contract (exponential backoff vs circuit breaker)
    2. Rate-limit (429) handling — wait+retry, queue, or fail-fast
    3. Response caching layer placement (prompt-level vs higher)
    4. MiniMax-M3 specific quirks (thinking mode, reasoning_content,
       1M context, prompt caching)
    """
    client = R1AuditClient()
    try:
        await client.verify_endpoint()
        result = await client.audit(
            target_files=[
                f"{repo_root}/backend/llm_client.py",
                f"{repo_root}/backend/r1_audit_client.py",
                f"{repo_root}/backend/api/action.py",
                f"{repo_root}/backend/turn_system.py",
            ],
            concerns=[
                "Retry contract: what is the right retry policy for MiniMax-M3? Current backend/llm_client.py uses httpx.Timeout + raise_for_status, no retry. Audit: (a) should we add tenacity-style exponential backoff (1s, 2s, 4s, cap at 30s) for transient 5xx + timeouts, (b) should we add a circuit breaker (open after N consecutive failures, half-open probe after cooldown), (c) which library — tenacity (already in requirements.txt!) or roll-our-own. Recommend the standard pattern for a 1M-context cloud LLM.",
                "Rate limit handling: MiniMax-M3 returns 429 on rate-limit. Current client raises on 4xx. Audit: how should the client react — (a) wait + retry with Retry-After header (respect server hint), (b) push to a local queue and return 202 Accepted to the caller, (c) fail-fast and let the caller (action endpoint) decide. Recommend the user-facing UX for a 1-3s scene-generation round-trip: a 5s+ wait is acceptable, a 30s+ wait is not.",
                "Response caching: many LLM responses are deterministic for the same prompt (e.g. lore lookups, deterministic scene templates). Should the client cache at the prompt level (sha256(prompt+model+temperature) → response, with TTL), or leave that to a higher layer (e.g. demo_integration, or a new @cached decorator on generate_scene)? Audit for the cleanest separation: a low-level client should not own a cache, but a high-level service layer probably should.",
                "MiniMax-M3 specific quirks: thinking mode is enabled by default, reasoning_content is separate from content, context window is 1M tokens (vs R1's 6K). Are there any framework-level changes needed to handle the thinking tokens? Specifically: (a) UI display — does the WebSocket payload expose reasoning_content to the frontend, and if so is that intentional (player sees the AI's thought process) or a leak? (b) Token counting — does the current response handler count reasoning_content toward output_tokens, inflating cost estimates? (c) Prompt caching — M3 supports Anthropic-style prompt caching; should the client set cache_control breakpoints for the system_prompt and world_lore blocks?",
            ],
            context={
                "phase": "D6",
                "current_state": "backend/llm_client.py v3.5 — real MiniMax-M3, response_format=json_object, no retry, no cache, no rate-limit handling",
                "model_config": {
                    "name": "MiniMax-M3",
                    "context": "1M tokens",
                    "thinking_mode": "on (default)",
                    "output_channels": ["content", "reasoning_content"],
                    "endpoint": "https://api.minimax.chat/v1",
                },
                "callers": [
                    "backend/api/action.py — per-action scene generation",
                    "backend/turn_system.py — turn-completion narration",
                ],
                "test_count": 161,
                "previous_r1_audits": [
                    "Round 1-3: R1AuditClient itself uses a similar httpx client pattern; Round 3 noted 'JSON parsing safety' as a finding (already mitigated by try/except in chat())",
                ],
            },
        )
        return result
    finally:
        await client.close()
