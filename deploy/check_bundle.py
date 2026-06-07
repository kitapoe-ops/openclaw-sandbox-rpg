"""Check the production JS bundle for issues."""
import sys
from pathlib import Path

bundle_path = next(
    Path(r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\frontend\dist\assets").glob(
        "index-*.js"
    )
)
bundle = bundle_path.read_text(encoding="utf-8")
print(f"Bundle: {bundle_path.name} ({len(bundle)} chars)")

# Check key patterns
checks = [
    "loadError",
    "useGameStore",
    "storeToRefs",
    "useRoute",
    "CharacterCreateView",
    "HomeView",
    "loadError=",
    "loadError =",
    'gameStore.loadError',
    'loadError=',
    'loadError.value',
]
for c in checks:
    pos = bundle.find(c)
    print(f"  {c:30s} : {pos}")
