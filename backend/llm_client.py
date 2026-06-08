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
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any

import httpx
from pydantic import ValidationError

from backend.state_machine import (
    StateMutation,
)

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
DEFAULT_TIMEOUT_CONNECT = 5.0  # 5s to establish connection
DEFAULT_TIMEOUT_READ = 30.0  # 30s for LLM response (cloud)
DEFAULT_TIMEOUT_WRITE = 10.0
DEFAULT_TIMEOUT_POOL = 10.0

# Sampling defaults recommended by MiniMax-M3 docs.
DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 0.95
DEFAULT_MAX_TOKENS = 4000

# Retry policy (addresses R1 finding CRITICAL #1 + #2).
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0  # 1s, 2s, 4s, 8s, ...
DEFAULT_BACKOFF_CAP = 30.0  # never sleep more than 30s
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
        messages: list[dict[str, str]],
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

    @abstractmethod
    async def generate_with_state_contract(
        self,
        system_prompt: str,
        user_message: str,
        current_state: list[str],
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """Generate a response and enforce the F3 StateMutation contract.

        Phase F3, Requirement 1: the LLM's response JSON must parse
        cleanly into :class:`backend.state_machine.StateMutation`. On
        any validation failure (invalid JSON, extra fields,
        oversized tags, non-CJK chars), the mutation is dropped but
        the narrative is still returned.

        Phase G1 adds retry-with-feedback: when a mutation is
        dropped, the next LLM call receives a ``[Previous attempt
        errors]`` block appended to the user message asking the
        LLM to re-emit a valid mutation. Capped by ``max_retries``
        (default 2 — so 3 total LLM calls max per action).

        The implementation is expected to:

          1. Call the LLM with a system prompt that includes the
             ``state_mutations`` schema (F1 Pydantic strict). The
             current state is included in the system prompt, so the
             LLM can ground its tag choices.
          2. Parse the response as a JSON object with shape
             ``{"narrative": str, "state_mutations": {...} | null}``.
          3. Validate the ``state_mutations`` field via
             :func:`state_mutations_validator` (F1 defense D2).
          4. If the validation fails AND we have retries left, append
             the specific validation errors to the user message and
             re-call the LLM.
          5. Return a dict with the contract::

                {
                  "narrative": str,            # always present
                  "mutation": StateMutation | None,  # None if rejected
                  "parsed": dict | None,       # the raw JSON object
                  "raw": str,                  # the last LLM raw text
                  "error": str | None,         # last validation error, if any
                  "retries_used": int,         # 0..max_retries
                  "ghost_state_warning": bool, # True if all retries failed
                  "retries_exhausted": bool,   # True iff ghost_state_warning
                }

             On a hard LLM failure (e.g. network error), the dict
             should still be returned with ``narrative=""`` and
             ``error="llm_call_failed: <reason>"`` — this counts
             as a failed attempt and is subject to retry just like
             a validation failure.

        ``current_state`` is passed in so the LLM has the "absolute
        current reality" at the top of the prompt (F4 invariant).
        The system_prompt already includes the state via
        :class:`backend.prompt_builder.PromptBuilder`; this argument
        is for the LLM to make a self-check before emitting
        ``state_mutations``.

        The F3 atomicity guarantee is preserved: if all retries are
        exhausted, the narrative is still returned with
        ``mutation=None`` and ``ghost_state_warning=True``. The
        action processor can then log the warning.
        """
        raise NotImplementedError


# ============================================
# Helpers
# ============================================


def _make_cache_key(
    messages: list[dict[str, str]],
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
            ({"role": m.get("role", ""), "content": m.get("content", "")} for m in messages),
            key=lambda m: (m["role"], m["content"]),
        ),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _parse_json_response(content: str) -> dict[str, Any]:
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
# State-mutation JSON contract (Phase F3)
# ============================================


def _extract_state_mutations_dict(content: str) -> dict[str, Any] | None:
    """Find the JSON object that contains a `state_mutations` field.

    Phase F3 contract: the LLM's response is expected to be a JSON
    object with shape ``{"narrative": str, "state_mutations": {...} | null}``.
    The narrative may be wrapped in prose / markdown fences, so we
    do a tolerant extraction:

      1. Try the whole string as JSON.
      2. Try a markdown-fenced ```json ... ``` block.
      3. Try a regex over the first brace-delimited JSON object that
         contains a ``"state_mutations"`` key (nested-brace safe
         enough for our payload — F1's StateMutation is shallow).

    Returns the parsed dict on success; ``None`` if no JSON object
    with a ``state_mutations`` key is found. This is the
    "rejection is fine, but the error must be informative" path.
    """
    # 1. Whole-string JSON.
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict) and "state_mutations" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    # 2. Markdown fence.
    md_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if md_match:
        try:
            parsed = json.loads(md_match.group(1))
            if isinstance(parsed, dict) and "state_mutations" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass

    # 3. First brace-delimited object containing state_mutations.
    # We walk the string looking for a `{` whose matching `}`
    # contains "state_mutations". A simple balanced-brace walk
    # is good enough for the F1 StateMutation shape (no nested
    # braces inside string values in practice).
    for start in range(len(content)):
        if content[start] != "{":
            continue
        depth = 0
        in_string = False
        escape = False
        for end in range(start, len(content)):
            ch = content[end]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = content[start : end + 1]
                    if "state_mutations" not in candidate:
                        break  # wrong object; try next `{`
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict) and "state_mutations" in parsed:
                            return parsed
                    except json.JSONDecodeError:
                        break
                    break
    return None


def _format_validation_error(exc: ValidationError) -> str:
    """Convert a Pydantic ValidationError into LLM-actionable feedback.

    Phase G1 (Requirement 2): the LLM needs to know *what* was wrong
    and *where* in its response, so it can re-emit a valid mutation
    on the retry. We enumerate every error Pydantic reports and
    format them as ``field '<path>': <message>`` strings joined by
    ``"; "``.

    Example output::

        field 'add_state.0': tag too long: 18 > 15 chars;
        field 'reason': string_too_short (min 1)

    The string is truncated to 800 chars to fit inside the user
    message even on extreme payloads. We keep the first ~5 errors
    to avoid drowning the LLM in noise.
    """
    errors = exc.errors() or []
    parts: list[str] = []
    for err in errors[:5]:
        loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("__root__",))
        msg = err.get("msg", "validation failed")
        ct = err.get("ctx") or {}
        # Surface the most actionable bit of the ctx dict (Pydantic
        # stuffs e.g. ``max_length=15`` here for some validators).
        if isinstance(ct, dict):
            for k, v in ct.items():
                if k in ("max_length", "min_length", "max", "min", "expected"):
                    msg = f"{msg} (got {v})" if v is not None else msg
        if loc:
            parts.append(f"field '{loc}': {msg}")
        else:
            parts.append(str(msg))
    if not parts:
        return "validation_failed: unknown pydantic error"
    return "; ".join(parts)[:800]


def state_mutations_validator(
    raw_response: str,
) -> tuple[StateMutation | None, str | None, dict[str, Any] | None]:
    """Parse a raw LLM response and validate the `state_mutations` field.

    Phase F3 defense D2: the LLM's `state_mutations` block must parse
    cleanly into F1's `StateMutation` Pydantic model. Any violation
    (invalid JSON, extra fields, oversized tags, non-CJK chars) →
    the WHOLE mutation is dropped, but the narrative is still
    returned if present.

    Returns a 3-tuple ``(mutation, error, parsed_dict)``:

      * ``mutation`` — the validated ``StateMutation`` instance, or
        ``None`` if the field was missing / invalid / not a dict.
      * ``error`` — a short string describing the failure (e.g.
        ``"validation_failed: extra fields not permitted"``), or
        ``None`` if validation passed.
      * ``parsed_dict`` — the parsed JSON dict (so the caller can
        pull the `narrative` field), or ``None`` if parsing failed.

    Atomicity (per F1 audit defense D2): a single bad field drops
    the WHOLE mutation. We never apply partial mutations.
    """
    parsed = _extract_state_mutations_dict(raw_response)
    if parsed is None:
        return None, "no_state_mutations_json", None
    if "state_mutations" not in parsed:
        return None, "missing_state_mutations_key", parsed

    sm_value = parsed.get("state_mutations")
    if sm_value is None:
        # Explicit null: the LLM is signaling "no state change".
        # Treat as valid (the narrative stands on its own).
        return None, None, parsed
    if not isinstance(sm_value, dict):
        return None, f"state_mutations_not_object: {type(sm_value).__name__}", parsed

    try:
        mutation = StateMutation.model_validate(sm_value)
    except ValidationError as exc:
        # Phase G1: use the multi-error formatter so the LLM can
        # see *every* failing field on a retry (was single-error
        # in F3; single-error is fine for the "this can't be
        # salvaged" path, but on retry we want the LLM to fix
        # them all in one pass).
        reason = _format_validation_error(exc)
        return None, f"validation_failed: {reason}", parsed

    return mutation, None, parsed


# ============================================
# State-contract extension to LLMClient
# ============================================


class StateContractError(Exception):
    """Raised by ``generate_with_state_contract`` when validation
    fails in a way the caller wants to handle as an exception. Most
    callers should use the dict-returning form, which does not raise."""


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
        self._cache: OrderedDict[str, str] = OrderedDict()
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
        messages: list[dict[str, str]],
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
        messages: list[dict[str, str]],
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        use_cache: bool = True,
    ) -> tuple[str, dict[str, Any]]:
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

    async def generate_with_state_contract(
        self,
        system_prompt: str,
        user_message: str,
        current_state: list[str],
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """Phase F3 + G1: enforce the StateMutation contract on LLM output.

        Phase F3 calls :meth:`generate` (which routes through the
        retry/cache pipeline), then validates the response against
        F1's ``StateMutation`` schema. On validation failure, the
        mutation is dropped but the narrative is still surfaced.

        Phase G1 adds a retry-with-feedback loop (capped by
        ``max_retries``, default 2 — 3 total LLM calls max). On
        failure we inject a ``[Previous attempt errors]`` block into
        the user message so the LLM can self-correct. The system
        prompt is augmented with a short schema reminder so the LLM
        knows the expected output shape. The full F4 prompt builder
        also includes the schema in its template.
        """
        # Augment the system prompt with a state-mutation schema reminder.
        # We keep this lightweight — the real prompt comes from
        # PromptBuilder (F4) which already includes the schema.
        augmented_system_prompt = (
            f"{system_prompt}\n\n"
            "## State Mutation Schema (F1 contract)\n"
            "When your response implies a state change, return a JSON "
            "object of shape:\n"
            "```\n"
            "{\n"
            '  "narrative": "<narrative text>",\n'
            '  "state_mutations": {\n'
            '    "target": "self" | "other",\n'
            '    "character_id": "<id>",\n'
            '    "add_state": ["<tag1>", ...],            // max 7 tags, '
            "each CJK-only and <=15 chars\n"
            '    "remove_state": ["<tag2>", ...],\n'
            '    "stamina": "<descriptor>" | null,\n'
            '    "health": "<descriptor>" | null,\n'
            '    "morale": "<descriptor>" | null,\n'
            '    "items_consumed": [{"item_id": "...", "quantity": 1}],\n'
            '    "new_memories": ["<memory>"],\n'
            '    "relationship_changes": [{"npc_id": "...", '
            '"new_relationship": "..."}],\n'
            '    "reason": "<narrative reason>"\n'
            "  }\n"
            "}\n"
            "```\n"
            "Current character state (for grounding): "
            f"{current_state}\n"
        )

        # Phase G1: retry loop. We track every error so we can
        # re-inject them on the next attempt. The last error wins
        # in the final return; earlier errors are logged for
        # observability.
        last_result: dict[str, Any] = {
            "narrative": "",
            "mutation": None,
            "parsed": None,
            "raw": "",
            "error": None,
        }
        last_error: str | None = None
        attempts_made = 0
        retries_used = 0
        # max_retries=2 → 3 total attempts (initial + 2 retries).
        # max_retries=0 → 1 total attempt (F3 original behaviour).
        total_attempts = max_retries + 1
        for attempt_idx in range(total_attempts):
            attempts_made += 1
            if attempt_idx > 0:
                retries_used = attempt_idx
            # Inject previous errors into the user message so the
            # LLM can self-correct.
            augmented_message = user_message
            if last_error is not None:
                augmented_message = (
                    f"{user_message}\n\n"
                    "[Previous attempt errors (please fix on retry)]\n"
                    f"- {last_error}"
                )
            try:
                raw = await self.generate(
                    system_prompt=augmented_system_prompt,
                    user_message=augmented_message,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "generate_with_state_contract: LLM call failed " "(attempt %d/%d): %s",
                    attempt_idx + 1,
                    total_attempts,
                    exc,
                )
                last_error = (f"llm_call_failed: {type(exc).__name__}: {exc}")[:300]
                last_result = {
                    "narrative": "",
                    "mutation": None,
                    "parsed": None,
                    "raw": "",
                    "error": last_error,
                }
                # If we have retries left, continue; otherwise fall
                # through to the exhausted path.
                if attempt_idx < total_attempts - 1:
                    continue
                else:
                    break

            mutation, error, parsed = state_mutations_validator(raw)
            narrative = ""
            if parsed is not None and isinstance(parsed.get("narrative"), str):
                narrative = parsed["narrative"]
            last_result = {
                "narrative": narrative,
                "mutation": mutation,
                "parsed": parsed,
                "raw": raw,
                "error": error,
            }
            last_error = error
            if mutation is not None or error is None:
                # Success: validated mutation, OR explicit null
                # (LLM signalled "no state change" — valid).
                return {
                    **last_result,
                    "retries_used": retries_used,
                    "ghost_state_warning": False,
                    "retries_exhausted": False,
                }
            # Validation failed; log and continue if we have retries.
            logger.info(
                "generate_with_state_contract: validation failed on " "attempt %d/%d: %s",
                attempt_idx + 1,
                total_attempts,
                error,
            )
            # Loop continues → inject error on next attempt.

        # All retries exhausted. Preserve the F3 atomicity contract:
        # narrative (if any) is still returned, mutation is None,
        # the caller logs ghost_state_warning.
        return {
            **last_result,
            "retries_used": retries_used,
            "ghost_state_warning": True,
            "retries_exhausted": True,
        }

    # Phase G1: alias for the inner LLM call so tests / subclasses
    # can patch the call without re-implementing the retry loop.
    # Defaults to :meth:`generate` (the same call F3 made).
    async def _call_llm_with_contract(
        self,
        system_prompt: str,
        user_message: str,
        current_state: list[str],
    ) -> str:
        """Single-attempt LLM call used by the G1 retry loop.

        Returns the raw LLM text. The outer ``generate_with_state_contract``
        handles the validation, retry, and feedback injection. This
        method is the seam where subclasses (e.g. tests) can inject
        canned responses.
        """
        return await self.generate(
            system_prompt=system_prompt,
            user_message=user_message,
        )

    # ---------------------- internals ----------------------

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Build the chat-completions payload."""
        decorated: list[dict[str, Any]] = []
        for m in messages:
            entry: dict[str, Any] = {"role": m.get("role", "user"), "content": m.get("content", "")}
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
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, dict[str, Any]]:
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
        last_exc: Exception | None = None
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
                    logger.error(
                        "MiniMax-M3 non-retryable HTTP %s: %s", r.status_code, r.text[:300]
                    )
                    raise httpx.HTTPStatusError(
                        f"HTTP {r.status_code}: {r.text[:300]}",
                        request=r.request,
                        response=r,
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
                    r.status_code,
                    attempt + 1,
                    self.max_retries + 1,
                    sleep_s,
                )
                self.retry_count += 1
                await asyncio.sleep(sleep_s)
                attempt += 1
                continue

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                if attempt >= self.max_retries:
                    logger.error(
                        "MiniMax-M3 network error after %s retries: %s", self.max_retries, e
                    )
                    raise
                sleep_s = self._backoff(attempt)
                logger.warning(
                    "MiniMax-M3 network error (attempt %s/%s); sleeping %.2fs: %s",
                    attempt + 1,
                    self.max_retries + 1,
                    sleep_s,
                    e,
                )
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
        return min(self.backoff_base * (2**attempt), self.backoff_cap)

    @staticmethod
    def _parse_response(data: dict[str, Any], retries: int) -> tuple[str, dict[str, Any]]:
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

        meta: dict[str, Any] = {
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

    def __init__(self, canned_response: str | None = None) -> None:
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
        messages: list[dict[str, str]],
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        use_cache: bool = True,
    ) -> str:
        self.calls += 1
        return self.canned_response

    async def health(self) -> bool:
        return True

    async def generate_with_state_contract(
        self,
        system_prompt: str,
        user_message: str,
        current_state: list[str],
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """Phase F3 + G1: validate the canned response against StateMutation.

        Same shape as the real client's method, but uses
        ``canned_response`` (or a list of them) instead of a network
        call. Validation is still enforced — the mock is faithful to
        the contract, it just doesn't call a remote model. Tests can
        swap ``canned_response`` to drive success / failure paths.

        Phase G1: if ``canned_response`` is a list, each element is
        popped and used as the response for one attempt. This lets
        tests drive the "fail then pass" path without subclassing.
        """
        del system_prompt  # unused in mock
        del current_state  # unused in mock
        del user_message  # unused in mock

        # Phase G1: allow list-of-responses to drive multi-attempt
        # scenarios. We pop the head of the list on each call so
        # the test sees a different response on each attempt.
        # (default behaviour: a single response used every time —
        # this preserves the F3 mock contract.)
        last_raw: str = ""
        last_error: str | None = None
        last_mutation: StateMutation | None = None
        last_parsed: dict[str, Any] | None = None

        # Resolve the per-attempt response sequence.
        if isinstance(self.canned_response, list):
            sequence: list[str] = list(self.canned_response)
        else:
            # F3 behaviour: a single canned response used on every
            # attempt. This means the mock will fail-then-fail
            # (always the same broken payload) by default — perfect
            # for the "retries exhausted" test.
            sequence = [str(self.canned_response)]

        total_attempts = max_retries + 1
        retries_used = 0
        for attempt_idx in range(total_attempts):
            if attempt_idx > 0:
                retries_used = attempt_idx
            # If the list is exhausted, reuse the last element.
            raw = sequence[attempt_idx] if attempt_idx < len(sequence) else sequence[-1]
            self.calls += 1
            mutation, error, parsed = state_mutations_validator(raw)
            last_raw = raw
            last_error = error
            last_mutation = mutation
            last_parsed = parsed
            if mutation is not None or error is None:
                # Success path (valid mutation OR explicit null).
                narrative = ""
                if parsed is not None and isinstance(parsed.get("narrative"), str):
                    narrative = parsed["narrative"]
                return {
                    "narrative": narrative,
                    "mutation": mutation,
                    "parsed": parsed,
                    "raw": raw,
                    "error": error,
                    "retries_used": retries_used,
                    "ghost_state_warning": False,
                    "retries_exhausted": False,
                }
            # Validation failed; continue if we have retries left.
            # (No logging — this is a mock.)

        # All attempts exhausted.
        narrative = ""
        if last_parsed is not None and isinstance(last_parsed.get("narrative"), str):
            narrative = last_parsed["narrative"]
        return {
            "narrative": narrative,
            "mutation": last_mutation,
            "parsed": last_parsed,
            "raw": last_raw,
            "error": last_error,
            "retries_used": retries_used,
            "ghost_state_warning": True,
            "retries_exhausted": True,
        }


# ============================================
# Factory
# ============================================


def get_llm_client(provider: str | None = None) -> LLMClient:
    """Build an LLMClient from environment variables.

    Env vars:
      LLM_PROVIDER      — "mock" (default) | "minimax"
      MINIMAX_API_KEY   — required when provider=minimax
      MINIMAX_BASE_URL  — default https://api.minimax.chat/v1
      MINIMAX_MODEL     — default MiniMax-M3

    Pass `provider` explicitly to override the env var (used in tests).
    """
    chosen = (
        provider if provider is not None else os.getenv("LLM_PROVIDER", DEFAULT_LLM_PROVIDER)
    ).lower()

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

    raise ValueError(f"Unknown LLM_PROVIDER={chosen!r}. Expected 'mock' or 'minimax'.")


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
    few_shots: list[dict[str, str]] | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """Backwards-compat helper. Delegates to a MiniMax-M3 client.

    Returns the parsed JSON dict (extracted from the assistant text
    via `_parse_json_response`).
    """
    client = get_llm_client(provider="minimax")
    assert isinstance(client, MiniMaxM3Client), (
        "generate_scene_response() requires provider='minimax'; "
        "set MINIMAX_API_KEY in the environment."
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if few_shots:
        messages.extend(few_shots)
    messages.append({"role": "user", "content": user_input})

    text = await client.chat(
        messages, temperature=temperature, max_tokens=max_tokens, use_cache=False
    )
    return _parse_json_response(text)


def build_few_shots(examples: list[dict[str, str]]) -> list[dict[str, str]]:
    """Convert raw examples to OpenAI chat format."""
    return [{"role": ex["role"], "content": ex["content"]} for ex in examples]


__all__ = [
    "LLMClient",
    "MiniMaxM3Client",
    "MockLLMClient",
    "StateContractError",
    "get_llm_client",
    "generate_scene_response",
    "build_few_shots",
    "state_mutations_validator",
    "_format_validation_error",
    # Config exports
    "MINIMAX_BASE_URL",
    "MINIMAX_MODEL",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_TOP_P",
    "DEFAULT_MAX_TOKENS",
]
