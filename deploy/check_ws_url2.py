"""Check if WS_BASE_URL is correctly inlined in the GameView bundle."""
import re
from pathlib import Path

gv_bundle = next(
    Path(r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\frontend\dist\assets").glob(
        "GameView-*.js"
    )
)
text = gv_bundle.read_text(encoding="utf-8")
print(f"Bundle: {gv_bundle.name} ({len(text)} chars)")

# Find WebSocket URL strings
for m in re.finditer(r"wss?://[a-zA-Z0-9.\-]+(?::\d+)?", text):
    print(f"  {m.group(0)}")

# Find "localhost:8000"
for m in re.finditer(r"localhost:8000", text):
    print(f"  localhost:8000 @ {m.start()}")
    print(f"  Context: {text[max(0, m.start()-100):m.end()+50]}")
