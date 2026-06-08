import asyncio
import os
import sys
import time
import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

async def test_raw_post():
    api_key = os.environ.get("MINIMAX_API_KEY", "")
    base_url = "https://api.minimax.chat/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # All English D&D prompt!
    payload = {
        "model": "MiniMax-M3",
        "messages": [
            {"role": "system", "content": "You are a D&D 5e Forgotten Realms expert. Generate a detailed location in Phandalin with id, name, description, interactables, atmosphere in English JSON format."},
            {"role": "user", "content": "Please generate for: loc_townmaster_hall."}
        ],
        "temperature": 1.0
    }
    
    print("Sending ALL ENGLISH D&D POST...")
    start_time = time.time()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(base_url, headers=headers, json=payload)
        elapsed = time.time() - start_time
        print(f"HTTP Status: {r.status_code} (took {elapsed:.2f} seconds)")
        print("Response body:", r.text[:1000])
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"Failed after {elapsed:.2f} seconds. Error:")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_raw_post())
