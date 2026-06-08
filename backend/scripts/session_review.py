#!/usr/bin/env python3
"""Session review: summarize the 5 commits made in this session.

Usage: python backend/scripts/session_review.py
"""
import subprocess
import sys

REPO = r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp"

COMMITS_THIS_SESSION = [
    ("3653a39", "docs: align test counts to 381 baseline"),
    ("ef21a97", "feat(prompt): 5-module UI tab + e2e tests + mock client compliance"),
    ("51afdb7", "feat(prompt): 5-module user prompt structure with choices array"),
    ("5626397", "feat(debug): Prompt Inspector dev-only read-only endpoint + panel"),
    ("1727c30", "docs+chore: align docs to current state, hide items/attitude systems"),
]


def run(cmd):
    return subprocess.check_output(cmd, cwd=REPO, shell=True, encoding="utf-8", errors="replace")


def stat(commit):
    out = run(f'git show --stat --format="" {commit}')
    return [l.strip() for l in out.splitlines() if l.strip() and "|" in l]


def files_changed(commit):
    out = run(f'git show --name-only --format="" {commit}')
    return [l.strip() for l in out.splitlines() if l.strip()]


def unstaged():
    out = run("git status --short")
    return [l for l in out.splitlines() if l.strip()]


def test_count():
    out = run('.venv\\Scripts\\python.exe -m pytest backend/tests/ -q --no-header -p no:cacheprovider 2>&1 | findstr /R "passed skipped failed"')
    return out.strip()


print("=" * 80)
print("SESSION REVIEW (2026-06-08)")
print("=" * 80)
print()

for short, subject in COMMITS_THIS_SESSION:
    print(f"### {short}  {subject}")
    print("-" * 80)
    files = files_changed(short)
    print(f"Files: {len(files)}")
    for f in files[:15]:
        print(f"  - {f}")
    if len(files) > 15:
        print(f"  ... and {len(files) - 15} more")
    print()

print("=" * 80)
print("UNSTAGED FILES (NOT in this session's commits)")
print("=" * 80)
un = unstaged()
unstaged_files = [l[3:] for l in un if l.startswith(" M") or l.startswith("??")]
for f in unstaged_files:
    print(f"  {f}")
print()
print(f"Total unstaged: {len(unstaged_files)}")
print()

print("=" * 80)
print("FINAL REGRESSION")
print("=" * 80)
print(test_count())
