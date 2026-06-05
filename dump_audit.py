import json
with open("docs/AUDIT_D2_RESULT.json", "r", encoding="utf-8") as f:
    data = json.load(f)
print("VERDICT:", data["verdict"])
print("ENDPOINT:", data["endpoint"])
print()
print("=== FINDINGS ===")
for i, f in enumerate(data["findings"], 1):
    print(f"\n[{i}] {f.get('severity')} | concern_index={f.get('concern_index')}")
    print(f"  Issue: {f.get('issue')}")
    print(f"  Evidence: {f.get('evidence')}")
    print(f"  Recommendation: {f.get('recommendation')}")
print()
print("=== RAW RESPONSE (first 5000 chars) ===")
print(data["raw_response"][:5000])
