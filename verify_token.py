"""Verify the Cloudflare API token. Build the 'Bearer ' prefix from
chr() to bypass any string-redaction (Telegram strips 'Bearer '
when rendering code)."""
import urllib.request
import urllib.error
import sys

env_path = r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\.env"
token = None
with open(env_path, encoding="utf-8") as f:
    for line in f:
        if line.startswith("CLOUDFLARE_API_TOKEN="):
            token = line.split("=", 1)[1].strip()
            break

if not token:
    print("ERROR: CLOUDFLARE_API_TOKEN not found in .env", file=sys.stderr)
    sys.exit(1)

# Build "Bearer " via chr() to avoid any renderer
BEARER = chr(66) + chr(101) + chr(97) + chr(114) + chr(101) + chr(114) + chr(32)
print(f"BEARER reconstructed: len={len(BEARER)}, value={BEARER!r}")
auth_str = BEARER + token
print(f"Auth string: len={len(auth_str)}, expected={7 + 53}={60}")

req = urllib.request.Request(
    "https://api.cloudflare.com/client/v4/user/tokens/verify",
    headers={
        "Authorization": auth_str,
        "Content-Type": "application/json",
    }
)

try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode()
        print(f"HTTP {resp.status}: {body}")
        if resp.status == 200 and '"success":true' in body:
            print("TOKEN IS VALID")
        sys.exit(0)
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"HTTP {e.code}: {body}")
    sys.exit(1)
