"""Read context around 'loadError' in the bundle."""
from pathlib import Path

bundle_path = next(
    Path(r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\frontend\dist\assets").glob(
        "index-*.js"
    )
)
bundle = bundle_path.read_text(encoding="utf-8")
pos = bundle.find("loadError")
print(f"loadError at {pos}")
print(bundle[max(0, pos - 100): pos + 200])
print()
# Also look for "setLoadError" to see if it's exported
p2 = bundle.find("setLoadError")
print(f"setLoadError at {p2}")
if p2 > -1:
    print(bundle[max(0, p2 - 100): p2 + 200])
