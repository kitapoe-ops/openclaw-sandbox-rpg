import asyncio
import httpx
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

async def test_local_llm():
    base_url = "http://127.0.0.1:1234/v1/chat/completions"
    payload = {
        "model": "qwen2.5-coder-7b-instruct", # or whatever model is loaded
        "messages": [
            {"role": "system", "content": "You are a D&D expert."},
            {"role": "user", "content": "Say hello in Traditional Chinese."}
        ],
        "temperature": 0.7
    }
    
    print(f"Testing Local LLM at {base_url}...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(base_url, json=payload)
        print(f"Status Code: {r.status_code}")
        print("Response:", r.json())
    except Exception as e:
        print("Local LLM failed:", e)

if __name__ == "__main__":
    asyncio.run(test_local_llm())
