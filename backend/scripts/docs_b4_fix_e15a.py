#!/usr/bin/env python3
"""Reorder PHASE_E1_5A_SUMMARY.md: move **Owner:** before the
Current state annotation, and ensure the annotation lands before `---`."""
from pathlib import Path
import re

p = Path(__file__).resolve().parents[2] / "docs" / "PHASE_E1_5A_SUMMARY.md"
text = p.read_text(encoding="utf-8")

# 1) Remove the orphan annotation that was inserted between Status and Owner
text = re.sub(r"\n>\s*\*\*Current state \(2026-06-08\):\*\*[^\n]*\n", "\n", text, count=1)
# 2) Insert the annotation AFTER the Owner line, before the `---` rule
text = re.sub(
    r"(\*\*Owner:\*\*[^\n]*)\n\n---\n",
    r"\1\n\n> **Current state (2026-06-08):** Test suite = **329 passed, 1 skipped, 0 fail (~10s)**. This phase's headline number above is preserved as shipped; full regression baseline is `pytest backend/tests/ -q`.\n\n---\n",
    text,
    count=1,
)
p.write_text(text, encoding="utf-8")
print("Fixed PHASE_E1_5A_SUMMARY.md")
