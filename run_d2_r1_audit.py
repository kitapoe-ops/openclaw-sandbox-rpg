"""Phase D2 R1-14B Real Audit — run a real R1 audit on the warning fixes."""
import asyncio
import json
import sys
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

from backend.r1_audit_client import R1AuditClient


async def main():
    client = R1AuditClient()
    try:
        # Pre-flight
        info = await client.verify_endpoint()
        print(f"Endpoint: {info['base_url']}  Model: {info['model']}")
        print(f"Available: {info['available_models']}")
        print()

        result = await client.audit(
            target_files=[
                "backend/demo_mode.py",
                "backend/tests/test_demo_mode_phase_d2.py",
                "pytest.ini",
            ],
            concerns=[
                "demo_mode.py: the fix to the never-awaited coroutine — is the fix semantically correct? Specifically, does the caching approach preserve the original DB-probe semantics (DEMO_MODE=true still forces demo, false still forces real DB, auto still tries DB first), and does the 'running loop short-circuit' (return False) avoid the asyncio.run-during-running-loop bug? Any regression risk in cache invalidation when callers reload the module?",
                "pytest.ini filterwarnings: does `ignore::starlette.exceptions.StarletteDeprecationWarning:fastapi.testclient` correctly suppress ONLY the Starlette httpx deprecation without hiding other relevant DeprecationWarnings, RuntimeWarnings, or UserWarnings from the project's own code? Could the pattern match be too broad or too narrow?",
                "Test suite after fix (target: 183+ passed, 0 StarletteDeprecation, 0 coroutine warnings): are there any new warnings introduced by the changes? Is the new test_demo_mode_phase_d2.py file sufficient regression coverage, or are there edge cases (e.g. concurrent DB probes, asyncio task spawning while probe is in flight) it misses?",
                "Production impact: does the fix change runtime behavior at scale? Specifically: (a) does the module-level cache break any pattern that re-imports demo_mode to detect DB state changes at runtime? (b) does the running-loop short-circuit cause the wrong answer in any production async context (e.g. the FastAPI app's first request vs subsequent requests)? (c) is there any race condition if two coroutines simultaneously call _test_db_connection before the cache is populated?",
            ],
            context={
                "phase": "D2",
                "warning_count_before": 2,
                "warning_count_after_target": 0,
                "warning_count_actual": 0,
                "tests_before": 167,
                "tests_after": 183,
                "files_modified": ["backend/demo_mode.py"],
                "files_created": ["pytest.ini", "backend/tests/test_demo_mode_phase_d2.py"],
                "demo_mode_lines_before": 59,
                "demo_mode_lines_after": 103,
                "root_cause": "asyncio.run(check()) inside _test_db_connection was called from main.py's async /health handler via FastAPI TestClient (anyio BlockingPortal). Anyio had a running event loop, asyncio.run raised RuntimeError, the coroutine check() was created but never awaited, GC finalizer warned. Fix: cache probe result + short-circuit when a loop is running.",
            },
        )

        # Persist the full raw response
        audit_log = Path("docs/AUDIT_D2_RESULT.json")
        audit_log.parent.mkdir(parents=True, exist_ok=True)
        audit_log.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Full audit log written to: {audit_log}")
        print()

        # Human-readable summary
        print("=" * 60)
        print(f"VERDICT: {result['verdict']}")
        print(f"FINDINGS: {len(result['findings'])}")
        print("=" * 60)
        for i, f in enumerate(result["findings"], 1):
            print(f"\n[{i}] {f.get('severity', '?')} — {f.get('issue', '?')}")
            print(f"    Evidence: {f.get('evidence', '?')[:200]}")
            print(f"    Recommendation: {f.get('recommendation', '?')[:200]}")
    except RuntimeError as e:
        print(f"R1 UNAVAILABLE: {e}", file=sys.stderr)
        # Save the prompt so it can be run later
        prompt_path = Path("docs/AUDIT_D2_PROMPT.md")
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(
            "# Phase D2 — R1 Audit Prompt (saved for later)\n\n"
            "R1 was unavailable when this audit was attempted. Below is the exact\n"
            "prompt that should be re-run when LM Studio is up and\n"
            "`deepseek-r1-distill-qwen-14b` is loaded.\n\n"
            "## Pre-flight\n"
            "1. Start LM Studio (Developer tab > Local Server > Enable, port 1234)\n"
            "2. Load `deepseek-r1-distill-qwen-14b`\n"
            "3. From the project root, run:\n\n"
            "```bash\n"
            ".venv/Scripts/python.exe run_d2_r1_audit.py\n"
            "```\n\n"
            "## Concerns (full list)\n\n"
            "1. demo_mode.py fix semantics (cache + running-loop short-circuit)\n"
            "2. pytest.ini filterwarnings scope (StarletteDeprecation only)\n"
            "3. Test coverage (test_demo_mode_phase_d2.py — 7 tests, edge cases?)\n"
            "4. Production impact (cache invalidation, race conditions, async handlers)\n",
            encoding="utf-8",
        )
        print(f"Prompt saved to: {prompt_path}", file=sys.stderr)
        sys.exit(2)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
