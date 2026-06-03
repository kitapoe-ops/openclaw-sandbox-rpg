"""
LLM Client (v3.5 — real MiniMax M3 integration)
================================================
Uses OpenAI-compatible API (matches minimax-portal provider).
Strict timeouts to prevent FastAPI background task hangs.

API endpoint: https://api.minimax.chat/v1/chat/completions
Model: MiniMax-M3
"""
import os
import json
import logging
import re
from typing import Dict, Any, Optional, List
import httpx

logger = logging.getLogger(__name__)


# ============================================
# Configuration
# ============================================
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M3")

# Strict timeouts to prevent death-window in FastAPI background tasks
DEFAULT_TIMEOUT_CONNECT = 5.0    # 5s to establish connection
DEFAULT_TIMEOUT_READ = 30.0      # 30s for LLM response (longer for cloud)
DEFAULT_TIMEOUT_WRITE = 10.0
DEFAULT_TIMEOUT_POOL = 10.0

DEFAULT_TEMPERATURE = 1.0        # M3 recommended
DEFAULT_TOP_P = 0.95             # M3 recommended
DEFAULT_MAX_TOKENS = 4000


# ============================================
# Main LLM call function
# ============================================
async def generate_scene_response(
    system_prompt: str,
    user_input: str,
    few_shots: Optional[List[Dict[str, str]]] = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Dict[str, Any]:
    """
    Call MiniMax M3 to generate scene output.
    Returns parsed JSON dict.

    Args:
        system_prompt: Scene Agent v2.0 system prompt
        user_input: Current context (character state + player choice + attitude)
        few_shots: Optional list of {"role": ..., "content": ...} for few-shot
        temperature: 1.0 recommended for M3
        max_tokens: 4000 typical for scene_output

    Returns:
        Parsed JSON dict with keys: scene_narrative, choices, state_changes, etc.
    """
    if not MINIMAX_API_KEY:
        raise ValueError("MINIMAX_API_KEY environment variable not set")

    messages = [{"role": "system", "content": system_prompt}]

    if few_shots:
        for shot in few_shots:
            messages.append(shot)

    messages.append({"role": "user", "content": user_input})

    payload = {
        "model": MINIMAX_MODEL,
        "messages": messages,
        "temperature": temperature,
        "top_p": DEFAULT_TOP_P,
        "max_tokens": max_tokens,
        # Force JSON output (critical for scene_output parsing)
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }

    timeout = httpx.Timeout(
        DEFAULT_TIMEOUT_READ,
        connect=DEFAULT_TIMEOUT_CONNECT,
        write=DEFAULT_TIMEOUT_WRITE,
        pool=DEFAULT_TIMEOUT_POOL,
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(
                f"{MINIMAX_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM API status error: {e.response.status_code} - {e.response.text}")
            raise
        except httpx.TimeoutException as e:
            logger.error(f"LLM API timeout: {e}")
            raise
        except httpx.RequestError as e:
            logger.error(f"LLM request error: {e}")
            raise

        data = response.json()

    # Extract content (M3 should return in standard OpenAI-compatible format)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        logger.error(f"Unexpected LLM response format: {data}")
        raise ValueError(f"Invalid LLM response structure: {e}")

    # Parse JSON from content
    # LLM might wrap in markdown code block, or add prose around it
    parsed = _parse_json_response(content)
    return parsed


def _parse_json_response(content: str) -> Dict[str, Any]:
    """
    Extract JSON from LLM response content.
    Handles:
    - Pure JSON: {"scene_narrative": ...}
    - Markdown wrapped: ```json\n{...}\n```
    - Prose + JSON: "Here is the scene:\n{...}"
    """
    # Try direct parse first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    md_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if md_match:
        try:
            return json.loads(md_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding first { to last }
    brace_match = re.search(r"\{.*\}", content, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from LLM response: {content[:500]}")


# ============================================
# Helper: Build few-shot examples
# ============================================
def build_few_shots(examples: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Convert raw examples to OpenAI chat format.
    Each example: {"role": "user|assistant", "content": "..."}
    """
    return [{"role": ex["role"], "content": ex["content"]} for ex in examples]


# ============================================
# Convenience: Build scene generation context
# ============================================
async def generate_scene(
    character_state: Dict[str, Any],
    world_lore_chunks: List[Dict[str, Any]],
    player_choice: Dict[str, Any],
    system_prompt: str,
    few_shots: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    High-level helper to generate a scene.

    Args:
        character_state: Current character semantic state
        world_lore_chunks: Retrieved chunks from LanceDB
        player_choice: Player's choice with attitude
        system_prompt: Scene Agent v2.0 system prompt
        few_shots: Optional few-shot examples

    Returns:
        Parsed scene_output JSON
    """
    # Build user input
    user_input_parts = [
        "## Current Character State",
        json.dumps(character_state, ensure_ascii=False, indent=2),
        "",
        "## World Lore (Retrieved)",
        _format_world_chunks(world_lore_chunks),
        "",
        "## Player's Choice",
        json.dumps(player_choice, ensure_ascii=False, indent=2),
    ]
    user_input = "\n".join(user_input_parts)

    return await generate_scene_response(
        system_prompt=system_prompt,
        user_input=user_input,
        few_shots=few_shots,
    )


def _format_world_chunks(chunks: List[Dict[str, Any]]) -> str:
    """Format retrieved world lore chunks for prompt injection."""
    sections = []
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        entity_type = meta.get("entity_type", "unknown")
        name = meta.get("name", "Unknown")
        sections.append(f"### {entity_type}: {name}")
        sections.append(chunk.get("content", ""))
        sections.append("")
    return "\n".join(sections)
