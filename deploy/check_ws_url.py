"""Check WebSocket URL configuration in production bundle."""
import re
from pathlib import Path

bundle_dir = Path(r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\frontend\dist\assets")
index_bundle = next(bundle_dir.glob("index-*.js"))
gv_bundle = next(bundle_dir.glob("GameView-*.js"))
ws_bundle = next(bundle_dir.glob("websocket-*.js"), None)

print(f"index bundle:  {index_bundle.name}")
print(f"GameView:      {gv_bundle.name}")
if ws_bundle:
    print(f"websocket:     {ws_bundle.name}")

for label, path in [("index", index_bundle), ("GameView", gv_bundle), ("websocket", ws_bundle)]:
    if path is None:
        continue
    text = path.read_text(encoding="utf-8")
    # All wss:// / ws:// strings
    matches = re.findall(r"wss?://[a-zA-Z0-9.\-]+(?::\d+)?(?:/[^\s\"']*)?", text)
    if matches:
        seen = set()
        for m in matches:
            if m not in seen:
                seen.add(m)
                print(f"  [{label}] {m}")
