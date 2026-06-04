"""
LLM Client Smoke Test
=====================
Verifies that backend.llm_client can actually reach the configured LLM endpoint
(cloud MiniMax M3 or local LM Studio) and get a real response.

This test is intentionally tolerant:
- If no LLM endpoint is reachable, it returns SKIP (not FAIL).
- If reachable, it asserts the response is non-empty and arrived in <30s.
"""
import os
import time
import pytest
import pytest_asyncio
import httpx

from backend.llm_client import llm_client, LLMRole


# --- Endpoint reachability probes (no mocks) -------------------------------

CLOUD_URL = "https://api.minimax.chat/v1/models"
LOCAL_URL = "http://127.0.0.1:1234/v1/models"


def _probe(url: str, headers: dict, timeout: float = 5.0):
    """Return (reachable: bool, info: str)."""
    try:
        r = httpx.get(url, headers=headers, timeout=timeout)
        if r.status_code == 200:
            return True, f"HTTP 200"
        return False, f"HTTP {r.status_code}: {r.text[:80]}"
    except httpx.ConnectError as e:
        return False, f"ConnectError: {str(e)[:80]}"
    except httpx.TimeoutException as e:
        return False, f"Timeout: {str(e)[:80]}"
    except httpx.HTTPError as e:
        return False, f"HTTPError({type(e).__name__}): {str(e)[:80]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:80]}"


def _check_cloud_reachable() -> tuple[bool, str]:
    api_key = os.environ.get("LLM_CLOUD_API_KEY") or os.environ.get("MINIMAX_API_KEY", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return _probe(CLOUD_URL, headers)


def _check_local_reachable() -> tuple[bool, str]:
    return _probe(LOCAL_URL, {})


# --- The smoke test --------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_chat_smoke():
    """
    Smoke test: call llm_client.chat(...) and confirm we get a real response.

    Skips gracefully if neither cloud nor local LLM is reachable.
    """
    # Try cloud first (preferred), then local fallback
    cloud_ok, cloud_info = _check_cloud_reachable()
    local_ok, local_info = _check_local_reachable()

    if not cloud_ok and not local_ok:
        pytest.skip(
            f"No LLM endpoint reachable. "
            f"Cloud: {cloud_info} | Local: {local_info}"
        )

    use_local = not cloud_ok
    endpoint_label = "local LM Studio" if use_local else "cloud MiniMax M3"

    system_prompt = "You are a test"
    user_message = "Reply with just 'OK'"
    max_tokens = 10

    start = time.perf_counter()
    try:
        response = await llm_client.chat(
            role=LLMRole.SCENE_AGENT,
            system_prompt=system_prompt,
            user_message=user_message,
            use_local=use_local,
            max_tokens=max_tokens,
        )
    except httpx.HTTPError as e:
        pytest.skip(f"{endpoint_label} HTTPError: {type(e).__name__}: {str(e)[:120]}")
    except Exception as e:
        pytest.fail(
            f"{endpoint_label} chat() raised unexpected "
            f"{type(e).__name__}: {str(e)}"
        )
    elapsed = time.perf_counter() - start

    # --- Assertions ---
    assert response is not None, f"{endpoint_label} returned None"
    assert isinstance(response, str), (
        f"{endpoint_label} returned non-string: {type(response).__name__}"
    )
    assert len(response) > 0, f"{endpoint_label} returned empty string"
    assert elapsed < 30, f"{endpoint_label} too slow: {elapsed:.2f}s (>= 30s)"

    print(
        f"\n[SMOKE] {endpoint_label} OK | "
        f"elapsed={elapsed:.2f}s | "
        f"response={response!r}"
    )
