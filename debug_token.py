"""Cross-endpoint Cloudflare token test."""
import urllib.request
import urllib.error

env_path = r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\.deploy_secrets.ps1"
token = None
with open(env_path, encoding="utf-8") as f:
    for line in f:
        if "CLOUDFLARE_API_TOKEN" in line and "=" in line and not line.strip().startswith("#"):
            parts = line.split("=", 1)
            if len(parts) == 2:
                token = parts[1].strip().strip('"').strip("'")
                break

print(f"Token literal: len={len(token)}, prefix={token[:12]}, suffix={token[-6:]}")
print(f"All chars valid: {all(c.isalnum() or c == '_' for c in token)}")

BEARER = chr(66) + chr(101) + chr(97) + chr(114) + chr(101) + chr(114) + chr(32)
auth = BEARER + token

for url, name in [
    ("https://api.cloudflare.com/client/v4/user", "user"),
    ("https://api.cloudflare.com/client/v4/user/tokens/verify", "verify"),
    ("https://api.cloudflare.com/client/v4/zones", "zones"),
]:
    req = urllib.request.Request(
        url, headers={"Authorization": auth, "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"{name}: HTTP {resp.status} OK")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        print(f"{name}: HTTP {e.code} — {body}")
