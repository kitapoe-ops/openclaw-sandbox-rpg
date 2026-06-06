"""
Pytest conftest at repo root (sandbox-rpg-tmp/).

Adds the project root to sys.path so that
`from backend.config import Settings` and
`from llm_client import ...` style imports resolve consistently
on both Windows (developer machines) and Linux (CI runner).

Background: the project has a flat layout — backend/ and
frontend/ are sibling directories, not Python packages. Pytest's
implicit "add parent dirs of test file to sys.path" works
most of the time but has edge cases (e.g. when the rootdir
is the parent of the test file, pytest's discovery can short-
circuit sys.path manipulation). This conftest makes the
sys.path setup explicit.

Test files should use the `from backend.X import Y` style
(preferred) or the `from X import Y` style if X is in the
same directory as the test file. The latter only works when
the test is in the same dir as the source module (e.g.
backend/tests/test_X.py importing from backend/X.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

# conftest.py is at sandbox-rpg-tmp/ (repo root)
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
