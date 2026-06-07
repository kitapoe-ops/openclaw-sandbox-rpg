"""List models loaded in LM Studio."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx


async def main() -> None:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("http://127.0.0.1:1234/v1/models")
        data = r.json()
        for m in data.get("data", []):
            model_id = m.get("id", "?")
            max_len = m.get("max_model_len", "?")
            print(f"  {model_id}  (max_context={max_len})")


asyncio.run(main())
