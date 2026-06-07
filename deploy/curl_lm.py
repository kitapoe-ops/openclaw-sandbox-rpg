"""Direct curl test to LM Studio with a simple JSON request."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx


async def main() -> None:
    body = {
        "model": "google/gemma-4-12b-qat",
        "messages": [
            {"role": "system", "content": "You are a JSON generator. Return only JSON. Start with {. End with }."},
            {"role": "user", "content": "Return this JSON: {\"hello\": \"world\"}"},
        ],
        "temperature": 0,
        "max_tokens": 100,
    }
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("http://127.0.0.1:1234/v1/chat/completions", json=body)
        print(f"Status: {r.status_code}")
        print(f"Body: {r.text[:500]}")


asyncio.run(main())
