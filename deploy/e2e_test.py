"""End-to-end test for the L2-E production stack.

Connects to the WebSocket, submits an action, and waits for
the scene_update. Prints the narrative + number of choices.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets


async def main() -> None:
    uri = "wss://rpg.kitahim.uk/ws/game/new_character_id"
    t0 = time.time()
    async with websockets.connect(uri) as ws:
        await ws.recv()  # ack
        print(f"  [{time.time() - t0:.1f}s] ack")
        await ws.send(
            json.dumps(
                {
                    "type": "action_submit",
                    "round": 1,
                    "choice": {
                        "id": "opt_a",
                        "vignette": "I look around the room",
                        "intent_category": "exploration",
                    },
                }
            )
        )
        await asyncio.wait_for(ws.recv(), timeout=15)
        print(f"  [{time.time() - t0:.1f}s] accepted")
        msg2 = await asyncio.wait_for(ws.recv(), timeout=60)
        data = json.loads(msg2)
        n = data.get("narrative", "")
        c = data.get("choices", [])
        print(f"  [{time.time() - t0:.1f}s] scene_update: {len(n)} chars, {len(c)} choices")
        ids = [x.get("id") for x in c]
        print(f"    choices: {ids}")
        if len(c) >= 4:
            print("    PASS — 4+ choices returned")
        else:
            print(f"    FAIL — only {len(c)} choices")


asyncio.run(main())
