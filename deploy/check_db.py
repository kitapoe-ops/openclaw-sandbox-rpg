"""Check action_history table directly via Python."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp")

from sqlalchemy import text
from backend.db import AsyncSessionLocal


async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT id, character_id, scene_id, execution_status, created_at "
                "FROM action_history ORDER BY created_at DESC LIMIT 5"
            )
        )
        rows = list(result)
        print(f"action_history rows: {len(rows)}")
        for r in rows:
            print(f"  {r}")


asyncio.run(main())
