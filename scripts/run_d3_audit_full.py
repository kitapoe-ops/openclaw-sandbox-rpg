"""Pre-flight R1-14B audit for Phase D3 — full JSON output."""
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
    # Save full JSON to a file (UTF-8 safe)
    with open("docs/AUDIT_D3_RESULT.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"Verdict: {result.get('verdict')}")
    print(f"Total findings: {len(result.get('findings', []))}")
    for f in result.get("findings", []):
        print(f"  [{f.get('severity', '?')}] {f.get('issue', '?')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
