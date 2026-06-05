"""Pre-flight R1-14B audit for Phase D3 — repository + embedding."""
import asyncio
import json
import sys

from backend.r1_audit_client import audit_phase_d3_repository


async def main() -> int:
    try:
        result = await audit_phase_d3_repository(".")
    except Exception as exc:  # noqa: BLE001
        print(f"AUDIT_FAILED: {exc!r}", file=sys.stderr)
        return 1
    print(f"Verdict: {result.get('verdict')}")
    print("Findings:")
    for f in result.get("findings", []):
        sev = f.get("severity", "?")
        issue = f.get("issue", "?")
        print(f"  [{sev}] {issue}")
    rs = result.get("reasoning_summary", "")
    if rs:
        print(f"Reasoning summary: {rs[:400]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
