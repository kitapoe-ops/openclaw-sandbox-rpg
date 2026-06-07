"""List characters in DB."""
import asyncio
import sys

sys.path.insert(0, r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp")

from sqlalchemy import text
from backend.db import AsyncSessionLocal


async def main():
    async with AsyncSessionLocal() as s:
        r = await s.execute(
            text(
                "SELECT character_id, name, current_scene_id, is_alive "
                "FROM character_states ORDER BY created_at DESC LIMIT 10"
            )
        )
        rows = list(r)
        print(f"Total characters in DB: {len(rows)}")
        for row in rows:
            print(f"  {row[0]:30s}  {str(row[1])[:20]:20s}  scene={row[2]}  alive={row[3]}")


asyncio.run(main())
