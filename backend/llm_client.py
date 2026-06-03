"""
LLM Client
============
Unified interface for cloud (MiniMax M3) and local (Qwen) LLM calls.

Reference: docs/PROMPTS/scene_agent_prompt.md
           docs/PROMPTS/sub_agent_prompt.md
           docs/PROMPTS/god_agent_prompt.md
"""
from typing import Dict, Any, List, Optional
from enum import Enum
import httpx

from .config import settings


class LLMRole(str, Enum):
    SCENE_AGENT = "scene_agent"
    SUB_AGENT = "sub_agent"
    GOD_AGENT = "god_agent"
    DEATH_NARRATOR = "death_narrator"
    EMBEDDING = "embedding"


class LLMClient:
    """
    Unified LLM client with provider switching.

    Cloud: MiniMax M3 (via minimax-portal)
    Local: Qwen2.5-14B-Instruct (via LM Studio :1234)

    TODO: Implement OpenAI-compatible client integration.
    """

    def __init__(self):
        self.cloud_client = None  # Will be initialized on first use
        self.local_client = None
        self.embedding_client = None

    async def chat(
        self,
        role: LLMRole,
        system_prompt: str,
        user_message: str,
        few_shots: Optional[List[Dict[str, str]]] = None,
        use_local: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Send a chat completion request.

        Args:
            role: Which agent is making the call
            system_prompt: The agent's system prompt
            user_message: The current request
            few_shots: Optional few-shot examples
            use_local: Force local LLM (for cost saving)
            temperature: Override default temperature
            max_tokens: Override default max_tokens

        Returns:
            The LLM's response text
        """
        messages = [{"role": "system", "content": system_prompt}]

        if few_shots:
            for shot in few_shots:
                messages.append(shot)

        messages.append({"role": "user", "content": user_message})

        if use_local and settings.llm_local_enabled:
            return await self._call_local(messages, temperature, max_tokens)
        else:
            return await self._call_cloud(messages, temperature, max_tokens)

    async def _call_cloud(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Call MiniMax M3 via OpenAI-compatible API.
        """
        url = f"{settings.llm_cloud_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.llm_cloud_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.llm_cloud_model,
            "messages": messages,
            "temperature": temperature or settings.llm_cloud_temperature,
            "top_p": settings.llm_cloud_top_p,
            "max_tokens": max_tokens or settings.llm_cloud_max_tokens,
        }

        async with httpx.AsyncClient(timeout=settings.llm_cloud_timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def _call_local(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Call local Qwen via LM Studio.
        """
        url = f"{settings.llm_local_base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": settings.llm_local_model,
            "messages": messages,
            "temperature": temperature or settings.llm_local_temperature,
            "top_p": settings.llm_local_top_p,
            "max_tokens": max_tokens or settings.llm_local_max_tokens,
        }

        async with httpx.AsyncClient(timeout=settings.llm_local_timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            # Local Qwen may output reasoning_content instead of content
            return (
                data["choices"][0]["message"].get("content")
                or data["choices"][0]["message"].get("reasoning_content", "")
            )

    async def embed(self, text: str) -> List[float]:
        """
        Generate embedding for text using Nomic Embed.
        """
        url = f"{settings.embedding_base_url}/embeddings"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": settings.embedding_model,
            "input": text,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]


# Global client instance
llm_client = LLMClient()
