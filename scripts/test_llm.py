import asyncio
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

# Try to load environment from .env via dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from backend.llm_client import get_llm_client

async def main():
    print("MINIMAX_API_KEY from env:", os.environ.get("MINIMAX_API_KEY", "NOT SET"))
    print("LLM_PROVIDER:", os.environ.get("LLM_PROVIDER", "NOT SET"))
    
    try:
        client = get_llm_client()
        print("Obtained LLM client:", type(client))
        is_healthy = await client.health()
        print("LLM health status:", is_healthy)
        
        # Test generate
        print("Testing generation...")
        resp = await client.generate("You are a helpful assistant.", "Say 'hello world' in Traditional Chinese.")
        print("Response:", resp)
    except Exception as e:
        print("Error encountered:", e)

if __name__ == "__main__":
    asyncio.run(main())
