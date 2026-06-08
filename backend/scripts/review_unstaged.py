#!/usr/bin/env python3
"""Review helper: print git diff --shortstat + last-commit for each
unstaged file so the user can decide what to do with them.

Run: python backend/scripts/review_unstaged.py
"""
import subprocess

REPO = r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp"

FILES = [
    "backend/__init__.py",
    "backend/api/character.py",
    "backend/api/scene.py",
    "backend/demo_mode.py",
    "backend/state_extractor.py",
    "backend/ws/game_socket.py",
    "frontend/src/services/api.ts",
    "frontend/src/stores/gameStore.ts",
    "frontend/src/views/CharacterCreateView.vue",
    "frontend/src/views/HomeView.vue",
]


def run(cmd):
    return subprocess.check_output(cmd, cwd=REPO, shell=True, encoding="utf-8", errors="replace").strip()


def stat(f):
    return run(f'git diff --shortstat "{f}"')


def last_commit(f):
    return run(f'git log -1 --format="%h %ad %s" --date=short -- "{f}"')


def first_20_lines_diff(f):
    out = run(f'git diff "{f}"')
    lines = out.splitlines()
    if not lines:
        return "(empty diff)"
    # show first 25 lines
    sample = "\n".join(lines[:25])
    if len(lines) > 25:
        sample += f"\n... ({len(lines) - 25} more lines)"
    return sample


print("=" * 80)
print("UNSTAGED FILES REVIEW (10 files, 2026-06-08)")
print("=" * 80)
print()

for f in FILES:
    print(f"### {f}")
    print(f"  diff stat:   {stat(f)}")
    print(f"  last commit: {last_commit(f)}")
    print()


print("=" * 80)
print("DIFF SAMPLES (first 25 lines of each diff)")
print("=" * 80)
print()

for f in FILES:
    print(f"--- {f} ---")
    print(first_20_lines_diff(f))
    print()
