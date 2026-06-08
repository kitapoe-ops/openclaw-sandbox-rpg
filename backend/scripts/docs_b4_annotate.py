#!/usr/bin/env python3
"""
B4 batch: prepend "Current state (2026-06-08)" annotation line to all
PHASE_*_SUMMARY.md files right after the existing status blockquote line.

Goal: keep historical test counts untouched (preserve ship-time fidelity)
while making the current 329-pass reality visible to any reader of
historical summaries.

Run: python backend/scripts/docs_b4_annotate.py
Idempotent: skips files that already have the marker line.
"""
from pathlib import Path
import sys

DOCS = Path(__file__).resolve().parents[2] / "docs"
MARKER = "> **Current state (2026-06-08):**"

ANNOTATION = (
    "> **Current state (2026-06-08):** Test suite = **329 passed, 1 skipped, 0 fail (~10s)**. "
    "This phase's headline number above is preserved as shipped; full regression baseline is `pytest backend/tests/ -q`.\n"
)

def find_status_blockquote(lines):
    """Return index of the first non-empty blockquote that holds a status line.

    Status line heuristic: a `> ` blockquote line containing 'Status' or 'Ship'
    or 'Shipped' or 'tests' or 'pass' or 'PASS' or 'regression'.
    Also handles `**Status:**` (no `> ` prefix) in the first 10 lines.
    """
    for i, line in enumerate(lines[:10]):
        s = line.strip()
        if s.startswith(MARKER):
            return None
        if s.startswith(">"):
            body = s.lstrip(">").strip()
            if any(kw in body for kw in ("Status", "Ship", "tests", "test", "PASS", "pass", "regression", "shipped", "wiring")):
                return i
        # Fallback: `**Status:**` or `**??Status:**` style (no blockquote)
        if s.startswith("**Status:") or s.startswith("**Status") or s.startswith("**??") and "Status" in s:
            return i
    return None

def find_insertion_point(lines, status_idx):
    """Given the start of the status block, find the end of the contiguous
    metadata block. End = first `---` horizontal rule, or first blank line
    followed by a non-metadata paragraph (i.e. a heading `#` or a paragraph
    that doesn't look like `**Key:** value`).
    """
    i = status_idx + 1
    # Scan contiguous metadata: lines that are either blank-within-block or
    # look like `**...**` emphasis. Stop at `---` or a `#` heading.
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("---") and len(s) <= 5:
            return i  # insert BEFORE the rule
        if s.startswith("#"):
            return i
        if s == "":
            # peek: if next non-blank is `**` metadata or `>` blockquote, continue
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                ns = lines[j].strip()
                if ns.startswith("**") or ns.startswith(">"):
                    i = j + 1
                    continue
            # else: blank ends the block; insert here
            return i
        # Non-metadata line in same block: insert here
        return i
    return len(lines)

def process_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if any(MARKER in line for line in lines[:20]):
        return "skip (already annotated)"
    idx = find_status_blockquote(lines)
    if idx is None:
        return "skip (no status line found in first 10 lines)"
    insert_at = find_insertion_point(lines, idx)
    # Ensure blank line separator before insertion
    if insert_at > 0 and lines[insert_at - 1].strip() != "":
        lines.insert(insert_at, "\n")
        insert_at += 1
    lines.insert(insert_at, ANNOTATION)
    new_text = "".join(lines)
    path.write_text(new_text, encoding="utf-8")
    return f"annotated (inserted at line {insert_at+1})"

def main():
    targets = sorted(DOCS.glob("PHASE_*_SUMMARY.md"))
    if not targets:
        print("No PHASE_*_SUMMARY.md found in docs/", file=sys.stderr)
        return 1
    print(f"Found {len(targets)} SUMMARY files")
    for p in targets:
        try:
            result = process_file(p)
            print(f"  {p.name}: {result}")
        except Exception as e:
            print(f"  {p.name}: ERROR {e}", file=sys.stderr)
            return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
