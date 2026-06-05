"""Phase E5 R1-14B Real Audit — verify the D2 HIGH finding (Cache Invalidation Risk) is resolved.

This script runs a real R1-14B audit on the new public cache-invalidation API
(`reset_demo_mode_cache()`) introduced in Phase E5. The original D2 audit flagged
this as HIGH severity. This audit must determine whether the implementation fully
resolves that finding, or whether residual issues remain.

Pre-flight: LM Studio must be running on :1234 with deepseek-r1-distill-qwen-14b
loaded. If unavailable, the script saves the prompt to docs/AUDIT_E5_PROMPT.md
for later re-run.
"""
import asyncio
import json
import sys
from pathlib import Path

# Ensure the project root is on sys.path so 'backend.r1_audit_client' imports cleanly
sys.path.insert(0, str(Path(__file__).parent))

from backend.r1_audit_client import R1AuditClient


CONCERNS = [
    # 1) Original D2 HIGH: cache invalidation — was the API sufficient?
    "D2 HIGH finding (cache invalidation risk): Is the new public API "
    "`reset_demo_mode_cache()` sufficient to replace the importlib.reload hack? "
    "Verify the API: (a) clears the `_db_reachable_cache`, "
    "(b) updates a `last_reset` timestamp, "
    "(c) is idempotent (calling twice produces the same end-state), "
    "(d) is documented in the module docstring. "
    "Also: does it correctly invalidate any ancillary state (e.g. a cached loop-detection "
    "result, a 'we are in demo mode' flag, or any other module-level memoized value)?",

    # 2) Original D2 MEDIUM: insufficient test coverage
    "D2 MEDIUM finding (insufficient test coverage): Do the new tests in "
    "`test_demo_mode_e5.py` cover the contract: "
    "(a) idempotency — calling reset twice in a row is safe and observable, "
    "(b) cache_status observability — `cache_status()` reflects state correctly after a reset, "
    "(c) reset actually triggers a re-probe (NOT just sets the cache to None and skips the probe), "
    "(d) regression for the D2 fix (no coroutine warning, no asyncio.run inside running loop)? "
    "Are there any missing edge cases (concurrent resets, reset during a probe, reset before any probe)?",

    # 3) Original D2 LOW: race condition
    "D2 LOW finding (race condition): The original audit flagged a potential race when "
    "multiple coroutines access the cache. Is the new public API thread-safe / async-safe? "
    "Note: in CPython single-threaded asyncio, most data races are impossible by GIL semantics, "
    "but document the invariant. Does the API avoid `await` inside the reset (so it stays "
    "synchronous and atomic)? Is there any case where reset + concurrent is_demo_mode() could "
    "return a stale value?",

    # 4) Regression check
    "Regression check: Are the 9 original D2 tests (`test_demo_mode_phase_d2.py`) still passing? "
    "Are there any new RuntimeWarnings, DeprecationWarnings, or coroutine-never-awaited warnings "
    "introduced by the public API? Does the new API break any existing caller (main.py, "
    "demo_integration.py, tests)?",

    # 5) Observability
    "Observability: Does the `cache_status()` function provide useful debug info? Specifically: "
    "(a) does it return the current cache value, "
    "(b) the last_reset timestamp, "
    "(c) a way to tell whether the cache is populated vs cleared? "
    "Should it also report whether the last reset was manual (via `reset_demo_mode_cache()`) "
    "vs implicit (via module reload)? Does the return type make the contract obvious (dataclass, "
    "TypedDict, or plain dict)?",
]


CONTEXT = {
    "phase": "E5",
    "d2_finding": "HIGH - Cache Invalidation Risk in demo_mode.py",
    "d2_verdict": "CONDITIONAL (with HIGH finding on cache invalidation)",
    "implementation": "Public API `reset_demo_mode_cache()` + `cache_status()` observability helper",
    "files_modified": ["backend/demo_mode.py"],
    "files_created": ["backend/tests/test_demo_mode_e5.py"],
    "d2_original_evidence": "backend/demo_mode.py:30-45 (cache used importlib.reload hack to invalidate)",
    "d2_original_recommendation": "Implement a mechanism to invalidate the cache when module reloads occur or DB state changes dynamically.",
}


TARGET_FILES = [
    "backend/demo_mode.py",
    "backend/tests/test_demo_mode_e5.py",
    "backend/tests/test_demo_mode_phase_d2.py",
]


async def main():
    client = R1AuditClient()
    try:
        # Pre-flight
        info = await client.verify_endpoint()
        print(f"Endpoint: {info['base_url']}  Model: {info['model']}")
        print(f"Available models: {info['available_models']}")
        print()

        # Run audit
        result = await client.audit(
            target_files=TARGET_FILES,
            concerns=CONCERNS,
            context=CONTEXT,
        )

        # Save raw response (human-readable)
        raw_path = Path("docs/AUDIT_E5_RAW.txt")
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(
            f"VERDICT: {result['verdict']}\n\n"
            f"FINDINGS ({len(result.get('findings', []))}):\n"
            + "\n".join(
                f"  [{f.get('severity', '?')}] {f.get('issue', '?')}\n"
                f"    evidence: {f.get('evidence', '?')}\n"
                f"    rec: {f.get('recommendation', '?')}"
                for f in result.get("findings", [])
            )
            + f"\n\nRAW:\n{result.get('raw_response', '')}",
            encoding="utf-8",
        )
        print(f"Raw transcript written to: {raw_path}")

        # Save full JSON result
        result_path = Path("docs/AUDIT_E5_RESULT.json")
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"JSON result written to: {result_path}")
        print()

        # Console summary
        print("=" * 60)
        print(f"VERDICT: {result['verdict']}")
        print(f"FINDINGS: {len(result.get('findings', []))}")
        print("=" * 60)
        for i, f in enumerate(result.get("findings", []), 1):
            print(f"\n[{i}] {f.get('severity', '?')} — {f.get('issue', '?')}")
            print(f"    Evidence: {f.get('evidence', '?')[:200]}")
            print(f"    Recommendation: {f.get('recommendation', '?')[:200]}")

        return result

    except RuntimeError as e:
        # R1 unavailable — fail-closed, save prompt for later
        print(f"\n❌ R1 UNAVAILABLE (fail-closed): {e}", file=sys.stderr)

        prompt_path = Path("docs/AUDIT_E5_PROMPT.md")
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(
            build_saved_prompt(target_files=TARGET_FILES, concerns=CONCERNS, context=CONTEXT),
            encoding="utf-8",
        )
        print(f"Prompt saved to: {prompt_path}", file=sys.stderr)
        print("Re-run after LM Studio is up with deepseek-r1-distill-qwen-14b loaded.", file=sys.stderr)
        sys.exit(2)
    finally:
        await client.close()


def build_saved_prompt(target_files, concerns, context):
    """Build the saved-prompt markdown if R1 is unavailable."""
    concerns_md = "\n".join(f"{i+1}. {c}" for i, c in enumerate(concerns))
    files_md = "\n".join(f"- `{p}`" for p in target_files)
    ctx_md = "\n".join(f"- **{k}**: {v}" for k, v in context.items())
    return (
        "# Phase E5 — R1-14B Audit Prompt (saved for later)\n\n"
        "R1 was unavailable when this audit was attempted. Below is the exact\n"
        "prompt that should be re-run when LM Studio is up and\n"
        "`deepseek-r1-distill-qwen-14b` is loaded.\n\n"
        "## Pre-flight\n"
        "1. Start LM Studio (Developer tab > Local Server > Enable, port 1234)\n"
        "2. Load `deepseek-r1-distill-qwen-14b`\n"
        "3. From the project root, run:\n\n"
        "```bash\n"
        ".venv/Scripts/python.exe run_e5_audit.py\n"
        "```\n\n"
        "## Target files\n\n"
        f"{files_md}\n\n"
        "## Context\n\n"
        f"{ctx_md}\n\n"
        "## Concerns (full list)\n\n"
        f"{concerns_md}\n"
    )


if __name__ == "__main__":
    asyncio.run(main())
