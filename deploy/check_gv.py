"""Check if setLoadError is correctly exported in the GameView bundle."""
from pathlib import Path

dist = Path(r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\frontend\dist\assets")
gv_files = sorted(dist.glob("GameView-*.js"), key=lambda p: p.stat().st_mtime, reverse=True)
print(f"Latest GameView chunk: {gv_files[0].name}")
text = gv_files[0].read_text(encoding="utf-8")
pos = text.find("setLoadError")
print(f"setLoadError @ {pos}")
if pos > -1:
    print(f"Context: {text[pos:pos+200]}")

# Look for "loadError" anywhere
for m in __import__("re").finditer(r"loadError", text):
    print(f"  loadError @ {m.start()}: {text[m.start():m.start()+80]}")
