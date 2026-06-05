"""
Tests for backend/llm_client.py — Phase D6 LLMClient interface + real MiniMax-M3 client.

These tests are network-free: they patch httpx.AsyncClient.post / .get
to drive the retry / 429 / cache / reasoning-content branches without
ever hitting api.minimax.chat.

Covered (10/10):
    1.  Abstract class cannot be instantiated
    2.  Mock client returns canned response
    3.  Mock client health() is True
    4.  Factory returns mock by default (no env set)
    5.  Factory returns MiniMaxM3Client when LLM_PROVIDER=minimax + key set
    6.  MiniMaxM3Client uses the api_key passed to __init__ (not env)
    7.  Retry on 429: second attempt returns 200, retry_count == 1
    8.  Retry exhausted raises after max_retries + 1 attempts
    9.  Response cache: same prompt twice = httpx called once
    10. reasoning_content handled separately from content (M3 quirk)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Ensure repo root is on sys.path so `from backend.llm_client import ...` works
# when pytest is invoked from the sandbox-rpg-tmp directory.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.llm_client import (  # noqa: E402
    LLMClient,
    MiniMaxM3Client,
    MockLLMClient,
    get_llm_client,
)


# ============================================
# 1. ABC cannot be instantiated
# ============================================


def test_abstract_class_cannot_instantiate():
    """LLMClient declares generate/chat/health as abstract; instantiating
    it directly must raise TypeError."""
    assert hasattr(LLMClient, "__abstractmethods__"), (
        "LLMClient should use abc.ABC + @abstractmethod"
    )
    # The set must include the 3 documented abstract methods.
    abstract = LLMClient.__abstractmethods__
    assert {"generate", "chat", "health"}.issubset(abstract), (
        f"LLMClient missing expected abstract methods; got {abstract}"
    )
    with pytest.raises(TypeError):
        LLMClient()  # type: ignore[abstract]


# ============================================
# 2. Mock client returns canned response
# ============================================


@pytest.mark.asyncio
async def test_mock_client_generate_returns_canned_response():
    """MockLLMClient.generate() returns the canned string (no network)."""
    canned = '{"scene_narrative": "You wake in a forest.", "choices": ["look", "walk"]}'
    client = MockLLMClient(canned_response=canned)

    text = await client.generate(
        system_prompt="You are a narrator.",
        user_message="Begin.",
    )
    assert text == canned
    assert client.calls == 1

    # chat() also returns the canned text and increments calls.
    text2 = await client.chat(
        messages=[{"role": "user", "content": "Continue."}],
    )
    assert text2 == canned
    assert client.calls == 2


# ============================================
# 3. Mock client health is True
# ============================================


@pytest.mark.asyncio
async def test_mock_client_health_is_true():
    """MockLLMClient.health() returns True — it has no network to fail on."""
    client = MockLLMClient()
    assert await client.health() is True

    # Even a custom canned response keeps health() True.
    client2 = MockLLMClient(canned_response="anything")
    assert await client2.health() is True


# ============================================
# 4. Factory returns mock by default
# ============================================


def test_factory_returns_mock_by_default(monkeypatch):
    """With no LLM_PROVIDER / MINIMAX_API_KEY in env, get_llm_client()
    must return a MockLLMClient (the default for safety)."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    client = get_llm_client()
    assert isinstance(client, MockLLMClient)
    assert not isinstance(client, MiniMaxM3Client)

    # Explicit None also falls back to mock.
    client2 = get_llm_client(provider=None)
    assert isinstance(client2, MockLLMClient)


# ============================================
# 5. Factory returns MiniMaxM3Client when LLM_PROVIDER=minimax
# ============================================


def test_factory_returns_minimax_when_env_set(monkeypatch):
    """With LLM_PROVIDER=minimax + MINIMAX_API_KEY set, the factory
    must return a MiniMaxM3Client configured with that key."""
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-from-env")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M3-test")

    client = get_llm_client()
    assert isinstance(client, MiniMaxM3Client)
    assert client.api_key == "test-key-from-env"
    assert client.base_url == "https://example.test/v1"
    assert client.model == "MiniMax-M3-test"


def test_factory_minimax_missing_key_raises(monkeypatch):
    """LLM_PROVIDER=minimax without MINIMAX_API_KEY must raise a
    descriptive ValueError — fail-closed at construction time."""
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    with pytest.raises(ValueError, match="MINIMAX_API_KEY"):
        get_llm_client()


def test_factory_unknown_provider_raises(monkeypatch):
    """Unknown provider string must raise — fail-closed, no silent mock."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        get_llm_client(provider="gpt-9000")


# ============================================
# 6. MiniMaxM3Client uses provided api_key (not env)
# ============================================


def test_minimax_client_uses_provided_api_key(monkeypatch):
    """The MiniMaxM3Client constructor must accept api_key as a parameter
    and use it directly — no os.environ reading inside __init__.

    This is the decoupling rule: the client is unit-testable without
    monkeypatching env vars. We verify by (a) clearing all env vars and
    (b) constructing with an explicit key, then (c) confirming the
    client reports that exact key."""
    for var in ("LLM_PROVIDER", "MINIMAX_API_KEY", "MINIMAX_BASE_URL", "MINIMAX_MODEL"):
        monkeypatch.delenv(var, raising=False)

    client = MiniMaxM3Client(
        api_key="explicit-key-not-from-env",
        base_url="https://stub.test/v1",
        model="stub-model",
    )
    assert client.api_key == "explicit-key-not-from-env"
    assert client.base_url == "https://stub.test/v1"
    assert client.model == "stub-model"


def test_minimax_client_empty_api_key_raises():
    """Empty api_key must be rejected at __init__ time — fail-closed."""
    with pytest.raises(ValueError, match="api_key"):
        MiniMaxM3Client(api_key="")
    with pytest.raises(ValueError, match="api_key"):
        MiniMaxM3Client(api_key=None)  # type: ignore[arg-type]


# ============================================
# 7. Retry on 429: first call 429, second call 200
# ============================================


def _build_minimax_client() -> MiniMaxM3Client:
    return MiniMaxM3Client(
        api_key="test-key",
        base_url="https://stub.test/v1",
        model="stub-model",
        max_retries=3,
        backoff_base=0.001,  # keep tests fast
        backoff_cap=0.01,
        timeout_connect=1.0,
        timeout_read=1.0,
    )


def _stub_200_response() -> Dict[str, Any]:
    return {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": '{"ok": true}'},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def _stub_response_with_429() -> MagicMock:
    """Build a MagicMock that mimics httpx.Response.status_code == 429."""
    response = MagicMock()
    response.status_code = 429
    response.headers = {"Retry-After": "0"}  # server hint
    response.text = "rate limited"
    response.json.side_effect = Exception("should not call .json() on 429")
    return response


def _stub_response_with_status(status: int, body: Optional[Dict[str, Any]] = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.headers = {}
    response.text = "ok" if status == 200 else "err"
    if body is not None:
        response.json.return_value = body
    return response


@pytest.mark.asyncio
async def test_retry_on_429(monkeypatch):
    """First call 429, second call 200: the client must retry and
    return the 200 body. retry_count must reflect exactly 1 retry."""
    client = _build_minimax_client()
    sleep_mock = AsyncMock()
    monkeypatch.setattr("backend.llm_client.asyncio.sleep", sleep_mock)

    responses = [
        _stub_response_with_429(),
        _stub_response_with_status(200, _stub_200_response()),
    ]

    # Each retry creates a new `async with httpx.AsyncClient(...)` block,
    # so the AsyncMock on `.post` must persist across yields — otherwise
    # the second attempt would re-start the side_effect list and also
    # see 429. Share one `post_mock` across all yielded client_mocks.
    post_mock = AsyncMock(side_effect=responses)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_async_client_cm(*args, **kwargs):
        client_mock = MagicMock()
        client_mock.post = post_mock
        yield client_mock

    monkeypatch.setattr(
        "backend.llm_client.httpx.AsyncClient", fake_async_client_cm
    )

    text, meta = await client.chat_with_meta(
        messages=[{"role": "user", "content": "hi"}],
        temperature=1.0,
        max_tokens=100,
        use_cache=False,
    )

    assert text == '{"ok": true}'
    assert meta["retries"] == 1
    assert client.retry_count == 1
    # We should have slept exactly once (between attempts 1 and 2).
    assert sleep_mock.await_count == 1
    # And httpx.post was called exactly twice (1 original + 1 retry).
    assert post_mock.await_count == 2


# ============================================
# 8. Retry exhausted raises
# ============================================


@pytest.mark.asyncio
async def test_retry_exhausted_raises(monkeypatch):
    """When every attempt returns 429, the client must raise after
    max_retries + 1 attempts (1 initial + 3 retries = 4 calls)."""
    client = _build_minimax_client()
    sleep_mock = AsyncMock()
    monkeypatch.setattr("backend.llm_client.asyncio.sleep", sleep_mock)

    # Share the post_mock across all `async with` yields so attempts
    # accumulate correctly.
    post_mock = AsyncMock(return_value=_stub_response_with_429())

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_async_client_cm(*args, **kwargs):
        client_mock = MagicMock()
        # Every call returns 429.
        client_mock.post = post_mock
        yield client_mock

    monkeypatch.setattr(
        "backend.llm_client.httpx.AsyncClient", fake_async_client_cm
    )

    with pytest.raises(RuntimeError, match="failed after"):
        await client.chat_with_meta(
            messages=[{"role": "user", "content": "hi"}],
            use_cache=False,
        )

    # max_retries=3 => 4 total attempts => 3 sleeps.
    assert sleep_mock.await_count == 3
    assert client.retry_count == 3
    assert post_mock.await_count == 4


# ============================================
# 9. Response cache: same prompt twice = one httpx call
# ============================================


@pytest.mark.asyncio
async def test_response_cache_hit_no_second_call(monkeypatch):
    """Two identical chat() calls with the same (messages, temperature,
    max_tokens, model) must result in a single httpx call. The second
    call must be served from the in-process LRU cache."""
    client = _build_minimax_client()
    post_mock = AsyncMock(return_value=_stub_response_with_status(200, _stub_200_response()))

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_async_client_cm(*args, **kwargs):
        client_mock = MagicMock()
        client_mock.post = post_mock
        yield client_mock

    monkeypatch.setattr(
        "backend.llm_client.httpx.AsyncClient", fake_async_client_cm
    )

    messages = [{"role": "user", "content": "stable prompt"}]
    text1, meta1 = await client.chat_with_meta(messages, temperature=0.5, max_tokens=100)
    text2, meta2 = await client.chat_with_meta(messages, temperature=0.5, max_tokens=100)

    assert text1 == text2 == '{"ok": true}'
    assert post_mock.await_count == 1, "httpx should be called only once for identical prompts"
    assert meta1["cached"] is False
    assert meta2["cached"] is True
    assert client.cache_misses == 1
    assert client.cache_hits == 1

    # Different temperature must miss the cache.
    text3, meta3 = await client.chat_with_meta(messages, temperature=0.7, max_tokens=100)
    assert meta3["cached"] is False
    assert post_mock.await_count == 2

    # use_cache=False must skip the cache.
    text4, meta4 = await client.chat_with_meta(messages, temperature=0.5, max_tokens=100, use_cache=False)
    assert meta4["cached"] is False
    assert post_mock.await_count == 3


# ============================================
# 10. reasoning_content handled separately
# ============================================


@pytest.mark.asyncio
async def test_minimax_handles_reasoning_content_separately(monkeypatch):
    """M3 returns `reasoning_content` separately from `content`. The
    client must:
      (a) NOT concatenate reasoning into the returned text.
      (b) Surface the reasoning string via meta['reasoning_content'].
      (c) Count reasoning_tokens in usage.completion_tokens_details.

    This guards R1 finding HIGH #4 (reasoning-content leak into the
    visible narrative) and HIGH #5 (token counting)."""
    client = _build_minimax_client()
    reasoning_text = "Let me think step by step... The hero wakes in a forest."
    visible_text = '{"scene_narrative": "You wake in a forest."}'

    stub_body = {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": visible_text,
                    "reasoning_content": reasoning_text,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 42,
            "completion_tokens": 17,
            "completion_tokens_details": {"reasoning_tokens": 31},
        },
    }
    post_mock = AsyncMock(return_value=_stub_response_with_status(200, stub_body))

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_async_client_cm(*args, **kwargs):
        client_mock = MagicMock()
        client_mock.post = post_mock
        yield client_mock

    monkeypatch.setattr(
        "backend.llm_client.httpx.AsyncClient", fake_async_client_cm
    )

    text, meta = await client.chat_with_meta(
        messages=[{"role": "user", "content": "begin"}],
        use_cache=False,
    )

    # (a) The returned text is exactly the visible content — no leak.
    assert text == visible_text
    assert reasoning_text not in text, "reasoning_content must not be concatenated into the visible text"

    # (b) Reasoning is surfaced via meta, separately.
    assert meta.get("reasoning_content") == reasoning_text

    # (c) Token counts are populated correctly.
    assert meta["prompt_tokens"] == 42
    assert meta["completion_tokens"] == 17
    assert meta["reasoning_tokens"] == 31


@pytest.mark.asyncio
async def test_minimax_handles_missing_reasoning_content(monkeypatch):
    """M2.x (no thinking mode) returns content but no reasoning_content.
    The client must handle that gracefully — meta['reasoning_content']
    absent, reasoning_tokens == 0."""
    client = _build_minimax_client()
    stub_body = {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": '{"ok": true}'},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }
    post_mock = AsyncMock(return_value=_stub_response_with_status(200, stub_body))

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_async_client_cm(*args, **kwargs):
        client_mock = MagicMock()
        client_mock.post = post_mock
        yield client_mock

    monkeypatch.setattr(
        "backend.llm_client.httpx.AsyncClient", fake_async_client_cm
    )

    text, meta = await client.chat_with_meta(
        messages=[{"role": "user", "content": "hi"}],
        use_cache=False,
    )
    assert text == '{"ok": true}'
    assert "reasoning_content" not in meta
    assert meta["reasoning_tokens"] == 0
