"""Pre-flight R1-14B audit for Phase D1 merge."""
import asyncio
from backend.r1_audit_client import audit_phase_d1_merge


async def main():
    try:
        result = await audit_phase_d1_merge(".")
        print(f"Verdict: {result['verdict']}")
        print(f"Findings: {len(result.get('findings', []))}")
        for f in result.get("findings", []):
            sev = f.get("severity", "?")
            issue = f.get("issue", "?")
            ev = f.get("evidence", "?")[:120]
            rec = f.get("recommendation", "?")[:200]
            print(f"  [{sev}] {issue}")
            print(f"    evidence: {ev}")
            print(f"    rec:      {rec}")
        return result
    except RuntimeError as e:
        print(f"R1 UNAVAILABLE (fail-closed): {e}")
        return {"verdict": "UNAVAILABLE", "error": str(e)}


if __name__ == "__main__":
    asyncio.run(main())
