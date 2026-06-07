"""List scenes in DB so we know which IDs are valid."""
import asyncio
import sys

sys.path.insert(0, r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp")

from sqlalchemy import text
from backend.db import AsyncSessionLocal


async def main():
    async with AsyncSessionLocal() as s:
        r = await s.execute(
            text("SELECT id, name, world_id, location_tag FROM scenes ORDER BY id LIMIT 50")
        )
        rows = list(r)
        print(f"Scenes in DB: {len(rows)}")
        for row in rows:
            print(f"  {row[0]:40s}  {row[1]:30s}  world={row[2]}")


asyncio.run(main())
