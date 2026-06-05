"""
LLM Client v4.0 — Real MiniMax-M3 with LLMClient interface
============================================================
Phase D6 redesign: introduces an abstract `LLMClient` interface so the
narrative layer (action.py, turn_system.py) is decoupled from the
provider. Two implementations are shipped:

  * `MiniMaxM3Client`  — real MiniMax-M3 cloud, with retry, 429 handling,
                          and content-hash keyed response cache.
  * `MockLLMClient`    — canned-response client for tests / offline use.

A `get_llm_client()` factory picks the implementation from the
`LLM_PROVIDER` env var (default: `"mock"`).

R1 audit (Phase D6 pre-flight) flagged 3 CRITICALs and 3 HIGH/MEDIUM
findings in the previous module — every one is addressed below:

  CRITICAL #1  Retry policy ............... exponential backoff w/ tenacity-style loop
  CRITICAL #2  Rate-limit (429) handling ... respect `Retry-After`, then bounded wait
  CRITICAL #3  Response caching ........... content-hash LRU dict, opt-in via use_cache
  HIGH #4      reasoning_content leak ..... both `content` and `reasoning_content` are
                                              surfaced in the return tuple (caller decides
                                              what to do — they are NOT concatenated)
  HIGH #5      Token counting ............. usage.tokens counted separately as
                                              `prompt_tokens`/`completion_tokens`/
                                              `reasoning_tokens` (if present)
  MEDIUM #6    Prompt caching headers ..... M3 supports `cache_control` breakpoints —
                                              we set them on system_prompt + world_lore
                                              blocks (Anthropic-style) so the cloud
                                              cache can re-use them across calls.

API endpoint: https://api.minimax.chat/v1/chat/completions (OpenAI-compatible,
NOT `/v1/messages` Anthropic-style).
Model: MiniMax-M3
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


# ============================================
# Configuration
# ============================================

# Default provider when LLM_PROVIDER env is unset.
DEFAULT_LLM_PROVIDER = "mock"

# MiniMax-M3 endpoint (OpenAI-compatible chat completions).
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M3")

# Strict timeouts to prevent death-window in FastAPI background tasks.
DEFAULT_TIMEOUT_CONNECT = 5.0     # 5s to establish connection
DEFAULT_TIMEOUT_READ = 30.0       # 30s for LLM response (cloud)
DEFAULT_TIMEOUT_WRITE = 10.0
DEFAULT_TIMEOUT_POOL = 10.0

# Sampling defaults recommended by MiniMax-M3 docs.
DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 0.95
DEFAULT_MAX_TOKENS = 4000

# Retry policy (addresses R1 finding CRITICAL #1 + #2).
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0        # 1s, 2s, 4s, 8s, ...
DEFAULT_BACKOFF_CAP = 30.0        # never sleep more than 30s
DEFAULT_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

# Response cache (addresses R1 finding CRITICAL #3).
DEFAULT_CACHE_MAX_ENTRIES = 256


# ============================================
# Abstract interface
# ============================================


class LLMClient(ABC):
    """Abstract interface for narrative-generation LLM calls.

    Phase D6 design: hides the provider (MiniMax-M3 / GPT-4 / mock) from
    the narrative layer. Same retry / rate-limit / cache contract for
    every implementation.

    All three methods are async; the factory function is sync.
    """

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        use_cache: bool = True,
    ) -> str:
        """Single-turn generation. Returns the assistant text only.

        Forwards to `chat()` with a 2-message history. Implementations may
        use cache to short-circuit identical requests.
        """
        raise NotImplementedError

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        use_cache: bool = True,
    ) -> str:
        """Multi-turn generation. Returns the assistant text only.

        `messages` is the OpenAI-style list: `[{"role": ..., "content": ...}, ...]`.
        """
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> bool:
        """Cheap liveness check (no generation). Returns True if reachable
        and the configured model is available, False otherwise.

        Implementations MUST NOT raise on a routine failure — they should
        return False and log a warning. The caller (startup probe) treats
        False as "degraded, fall back to mock".
        """
        raise NotImplementedError


# ============================================
# Helpers
# ============================================


def _make_cache_key(
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: int,
    model: str,
) -> str:
    """Stable content-hash key for the response cache.

    Same prompt + same sampling + same model = same key, regardless of
    list ordering in `messages` (we sort by role+content before hashing).
    """
    payload = {
        "model": model,
        "temperature": round(float(temperature), 4),
        "max_tokens": int(max_tokens),
        "messages": sorted(
            ({"role": m.get("role", ""), "content": m.get("content", "")}
             for m in messages),
            key=lambda m: (m["role"], m["content"]),
        ),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _parse_json_response(content: str) -> Dict[str, Any]:
    """Extract JSON from a (possibly prose-wrapped) LLM response.

    Handles:
      * Pure JSON
      * Markdown-fenced ```json ... ```
      * Prose around a JSON object

    The previous v3.5 module used the same heuristic; we keep it so
    any caller of the module-level `generate_scene_response` keeps
    working.
    """
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    md_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if md_match:
        try:
            return json.loads(md_match.group(1))
        except json.JSONDecodeError:
            pass

    brace_match = re.search(r"\{.*\}", content, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from LLM response: {content[:500]}")


# ============================================
# Real implementation: MiniMax-M3
# ============================================


class MiniMaxM3Client(LLMClient):
    """Real MiniMax-M3 cloud client.

    Features (all addressing R1 findings CRITICAL #1–3, HIGH #4–5,
    MEDIUM #6 from the Phase D6 pre-flight audit):

      * **Exponential-backoff retry** (1s, 2s, 4s, …) on transient
        5xx / 408 / 429. Total retries bounded by `max_retries`.
      * **Rate-limit handling** — on 429 we sleep for
        `min(Retry-After, backoff_cap)` (server hint wins), then retry.
      * **Response cache** — `OrderedDict` LRU keyed by content hash.
        Bypassed when `use_cache=False`.
      * **Reasoning-content aware** — M3 returns `reasoning_content`
        separately from `content`. We never concatenate them; the
        `chat_with_meta()` method exposes both so the caller can decide
        whether to surface thinking tokens to the UI.
      * **Token counting** — `usage.prompt_tokens` and
        `usage.completion_tokens` are surfaced as `prompt_tokens` /
        `completion_tokens` / `reasoning_tokens` (when present).
      * **Prompt caching** — `cache_control` breakpoints on the
        system_prompt + world_lore blocks (Anthropic-style; M3 passes
        them through).

    The constructor accepts `api_key` and `base_url` as parameters —
    it does NOT read from env directly. The `get_llm_client()` factory
    is the only place that does env-reading. This keeps the client
    unit-testable (no monkey-patching of os.environ required for the
    common case).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = MINIMAX_BASE_URL,
        model: str = MINIMAX_MODEL,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_cap: float = DEFAULT_BACKOFF_CAP,
        cache_max_entries: int = DEFAULT_CACHE_MAX_ENTRIES,
        timeout_connect: float = DEFAULT_TIMEOUT_CONNECT,
        timeout_read: float = DEFAULT_TIMEOUT_READ,
        timeout_write: float = DEFAULT_TIMEOUT_WRITE,
        timeout_pool: float = DEFAULT_TIMEOUT_POOL,
    ) -> None:
        if not api_key:
            raise ValueError(
                "MiniMaxM3Client requires a non-empty `api_key`. "
                "Use the `get_llm_client()` factory to read it from env."
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.cache_max_entries = cache_max_entries

        self._timeout = httpx.Timeout(
            timeout_read,
            connect=timeout_connect,
            write=timeout_write,
            pool=timeout_pool,
        )
        self._cache: "OrderedDict[str, str]" = OrderedDict()
        # Bookkeeping for tests / observability.
        self.retry_count: int = 0
        self.cache_hits: int = 0
        self.cache_misses: int = 0

    # ---------------------- public API ----------------------

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        use_cache: bool = True,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        return await self.chat(
            messages, temperature=temperature, max_tokens=max_tokens, use_cache=use_cache
        )

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        use_cache: bool = True,
    ) -> str:
        """Multi-turn chat. Returns the assistant text only.

        Use `chat_with_meta()` if you also need `reasoning_content` or
        token usage (Phase D6 R1 finding HIGH #4 + #5).
        """
        text, _meta = await self.chat_with_meta(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            use_cache=use_cache,
        )
        return text

    async def chat_with_meta(
        self,
        messages: List[Dict[str, str]],
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        use_cache: bool = True,
    ) -> Tuple[str, Dict[str, Any]]:
        """Multi-turn chat. Returns (assistant_text, meta).

        `meta` keys:
          * `prompt_tokens`      — from usage.prompt_tokens
          * `completion_tokens`  — from usage.completion_tokens
          * `reasoning_tokens`   — from usage.completion_tokens_details.reasoning_tokens
                                   (M3-specific, may be 0 or absent)
          * `cached`             — True if served from the response cache
          * `retries`            — number of retries used on this call
        """
        cache_key = _make_cache_key(messages, temperature, max_tokens, self.model)
        if use_cache and cache_key in self._cache:
            # Move to end (LRU touch).
            self._cache.move_to_end(cache_key)
            self.cache_hits += 1
            return self._cache[cache_key], {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "reasoning_tokens": 0,
                "cached": True,
                "retries": 0,
            }

        self.cache_misses += 1
        text, meta = await self._post_with_retry(messages, temperature, max_tokens)

        if use_cache:
            self._cache[cache_key] = text
            self._cache.move_to_end(cache_key)
            while len(self._cache) > self.cache_max_entries:
                self._cache.popitem(last=False)

        meta["cached"] = False
        return text, meta

    async def health(self) -> bool:
        """Check `/models` — does the configured model appear?
        Returns False on any error (network, 4xx, 5xx, missing model).
        Never raises.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
            if r.status_code != 200:
                logger.warning("MiniMax-M3 /models returned HTTP %s", r.status_code)
                return False
            data = r.json()
            ids = [m.get("id", "") for m in data.get("data", [])]
            return self.model in ids
        except Exception as e:  # noqa: BLE001 — health check, must not raise
            logger.warning("MiniMax-M3 health check failed: %s", e)
            return False

    # ---------------------- internals ----------------------

    def _build_payload(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> Dict[str, Any]:
        """Build the chat-completions payload, with M3 prompt-cache hints."""
        # Phase D6 R1 finding MEDIUM #6: add cache_control breakpoints on
        # the system message and the first user message (typically the
        # world_lore block). M3 supports Anthropic-style breakpoints.
        decorated: List[Dict[str, Any]] = []
        for idx, m in enumerate(messages):
            entry: Dict[str, Any] = {"role": m.get("role", "user"), "content": m.get("content", "")}
            if idx < 2:  # system + first user block
                entry["cache_control"] = {"type": "ephemeral"}
            decorated.append(entry)

        return {
            "model": self.model,
            "messages": decorated,
            "temperature": temperature,
            "top_p": DEFAULT_TOP_P,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

    async def _post_with_retry(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> Tuple[str, Dict[str, Any]]:
        """POST with exponential-backoff retry on transient errors.

        R1 findings addressed:
          CRITICAL #1 — retry on transient 5xx / 408 / 425 / 429.
          CRITICAL #2 — 429 waits for `Retry-After` header (capped).
        """
        payload = self._build_payload(messages, temperature, max_tokens)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        attempt = 0
        last_exc: Optional[Exception] = None
        self.retry_count = 0
        while True:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    r = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                if r.status_code == 200:
                    return self._parse_response(r.json(), retries=attempt)

                if r.status_code not in DEFAULT_RETRYABLE_STATUS:
                    # Non-retryable status (4xx other than the ones above).
                    logger.error("MiniMax-M3 non-retryable HTTP %s: %s",
                                 r.status_code, r.text[:300])
                    raise httpx.HTTPStatusError(
                        f"HTTP {r.status_code}: {r.text[:300]}",
                        request=r.request, response=r,
                    )

                # Retryable status. Decide whether to retry or give up.
                if attempt >= self.max_retries:
                    # We've used all our retries — give up with a
                    # descriptive error (R1 finding CRITICAL #2).
                    raise RuntimeError(
                        f"MiniMax-M3 call failed after {self.max_retries + 1} "
                        f"attempts; last status={r.status_code} body={r.text[:200]}"
                    )

                # Honor Retry-After (R1 finding CRITICAL #2).
                retry_after = r.headers.get("Retry-After")
                if retry_after is not None:
                    try:
                        sleep_s = min(float(retry_after), self.backoff_cap)
                    except ValueError:
                        sleep_s = self._backoff(attempt)
                else:
                    sleep_s = self._backoff(attempt)

                logger.warning(
                    "MiniMax-M3 transient HTTP %s (attempt %s/%s); sleeping %.2fs",
                    r.status_code, attempt + 1, self.max_retries + 1, sleep_s,
                )
                self.retry_count += 1
                await asyncio.sleep(sleep_s)
                attempt += 1
                continue

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                if attempt >= self.max_retries:
                    logger.error("MiniMax-M3 network error after %s retries: %s",
                                 self.max_retries, e)
                    raise
                sleep_s = self._backoff(attempt)
                logger.warning("MiniMax-M3 network error (attempt %s/%s); sleeping %.2fs: %s",
                               attempt + 1, self.max_retries + 1, sleep_s, e)
                self.retry_count += 1
                await asyncio.sleep(sleep_s)
                attempt += 1
                continue

        # Unreachable — the loops above either return, raise, or continue.
        raise RuntimeError(
            f"MiniMax-M3 call failed after {self.max_retries + 1} attempts; last error: {last_exc}"
        )  # pragma: no cover

    def _backoff(self, attempt: int) -> float:
        """Exponential backoff: base, 2*base, 4*base, ... capped at backoff_cap."""
        return min(self.backoff_base * (2 ** attempt), self.backoff_cap)

    @staticmethod
    def _parse_response(data: Dict[str, Any], retries: int) -> Tuple[str, Dict[str, Any]]:
        """Extract text + token usage from the chat-completions JSON.

        M3 returns `reasoning_content` separately from `content`. We
        surface both, but we DO NOT concatenate them — that was R1
        finding HIGH #4 (concatenation inflates visible narrative).
        """
        try:
            choice = data["choices"][0]
            message = choice["message"]
            text = message.get("content", "") or ""
            reasoning = message.get("reasoning_content", "") or ""
        except (KeyError, IndexError, TypeError) as e:
            logger.error("Unexpected MiniMax-M3 response shape: %s", data)
            raise ValueError(f"Invalid MiniMax-M3 response structure: {e}") from e

        usage = data.get("usage", {}) or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        details = usage.get("completion_tokens_details", {}) or {}
        reasoning_tokens = int(details.get("reasoning_tokens", 0) or 0)

        meta: Dict[str, Any] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "reasoning_tokens": reasoning_tokens,
            "retries": retries,
        }
        # Reasoning content is carried via meta so callers can decide
        # whether to expose it (e.g. for the audit-trail UI). We
        # explicitly do NOT merge it into the returned text.
        if reasoning:
            meta["reasoning_content"] = reasoning
        return text, meta


# ============================================
# Mock implementation (tests + offline)
# ============================================


class MockLLMClient(LLMClient):
    """Mock LLM client — canned responses, no network, no retry, no cache.

    Used in unit tests (deterministic) and in environments without a
    MiniMax-M3 API key (developer machines, CI without secrets).
    """

    def __init__(self, canned_response: Optional[str] = None) -> None:
        self.canned_response = canned_response or (
            '{"scene_narrative": "Mock scene.", "choices": []}'
        )
        self.calls: int = 0

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        use_cache: bool = True,
    ) -> str:
        self.calls += 1
        return self.canned_response

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        use_cache: bool = True,
    ) -> str:
        self.calls += 1
        return self.canned_response

    async def health(self) -> bool:
        return True


# ============================================
# Factory
# ============================================


def get_llm_client(provider: Optional[str] = None) -> LLMClient:
    """Build an LLMClient from environment variables.

    Env vars:
      LLM_PROVIDER      — "mock" (default) | "minimax"
      MINIMAX_API_KEY   — required when provider=minimax
      MINIMAX_BASE_URL  — default https://api.minimax.chat/v1
      MINIMAX_MODEL     — default MiniMax-M3

    Pass `provider` explicitly to override the env var (used in tests).
    """
    chosen = (provider if provider is not None else os.getenv("LLM_PROVIDER", DEFAULT_LLM_PROVIDER)).lower()

    if chosen in ("mock", "mockllm", "mock-llm", "mock_llm"):
        return MockLLMClient()

    if chosen in ("minimax", "minimax-m3", "minimax_m3", "minimaxm3"):
        api_key = os.getenv("MINIMAX_API_KEY", "")
        if not api_key:
            raise ValueError(
                "LLM_PROVIDER=minimax but MINIMAX_API_KEY is not set. "
                "Set it in the environment or use provider='mock'."
            )
        return MiniMaxM3Client(
            api_key=api_key,
            base_url=os.getenv("MINIMAX_BASE_URL", MINIMAX_BASE_URL),
            model=os.getenv("MINIMAX_MODEL", MINIMAX_MODEL),
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER={chosen!r}. Expected 'mock' or 'minimax'."
    )


# ============================================
# Backwards-compat module-level helpers
# ============================================
#
# The previous v3.5 module exposed `generate_scene_response` and
# `generate_scene` as plain async functions that called MiniMax-M3
# directly. We keep the signatures and behaviour for any external
# caller (e.g. ad-hoc scripts under `scripts/`) by routing them
# through the factory's MiniMax-M3 client. This is intentionally
# the only place outside the factory that touches env vars — the
# narrative layer (`api/action.py`, `turn_system.py`) should switch
# to `get_llm_client()` directly in a follow-up refactor.


async def generate_scene_response(
    system_prompt: str,
    user_input: str,
    few_shots: Optional[List[Dict[str, str]]] = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Dict[str, Any]:
    """Backwards-compat helper. Delegates to a MiniMax-M3 client.

    Returns the parsed JSON dict (extracted from the assistant text
    via `_parse_json_response`).
    """
    client = get_llm_client(provider="minimax")
    assert isinstance(client, MiniMaxM3Client), (
        "generate_scene_response() requires provider='minimax'; "
        "set MINIMAX_API_KEY in the environment."
    )
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if few_shots:
        messages.extend(few_shots)
    messages.append({"role": "user", "content": user_input})

    text = await client.chat(
        messages, temperature=temperature, max_tokens=max_tokens, use_cache=False
    )
    return _parse_json_response(text)


def build_few_shots(examples: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Convert raw examples to OpenAI chat format."""
    return [{"role": ex["role"], "content": ex["content"]} for ex in examples]


__all__ = [
    "LLMClient",
    "MiniMaxM3Client",
    "MockLLMClient",
    "get_llm_client",
    "generate_scene_response",
    "build_few_shots",
    # Config exports
    "MINIMAX_BASE_URL",
    "MINIMAX_MODEL",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_TOP_P",
    "DEFAULT_MAX_TOKENS",
]
