"""Load test through the gateway.

    python client.py          # plain prompts via the Ollama-compatible /generate (no retrieval)
    python client.py --rag    # KiloTech RAG jobs (task kilotech_rag: retrieval + weather + LLM)
"""
import argparse
import asyncio
import httpx
import time

GATEWAY = "http://localhost:8000"

RAG_QUERIES = [
    "When should I plant kalo?",
    "How do I control pests on sweet potato?",
    "What is a lo'i and how is it built?",
    "Which native plants grow well in dry lowland areas?",
]

async def send_request(i, rag):
    await asyncio.sleep(i * 10)
    print(f"{time.time():.2f} -> Sending request {i}")
    if rag:
        url = f"{GATEWAY}/v1/generate"
        payload = {"task": "kilotech_rag", "model": "qwen2.5:3b",
                   "input": {"query": RAG_QUERIES[i % len(RAG_QUERIES)]}}
    else:
        url = f"{GATEWAY}/generate"
        payload = {
            "model": "qwen2.5:3b",
            "prompt": f"Hello, #{i}",
            "stream": False
        }
        if i == 0:
            payload["prompt"] = "Write me an essay of at least 1500 words about the history of Georgia Tech."

    async with httpx.AsyncClient(timeout=300) as client:
        try:
            response = await client.post(url, json=payload, params={"timeout_s": 280} if rag else None)
            data = response.json()
            if rag:
                if response.status_code != 200:
                    print(f"Request {i} failed: HTTP {response.status_code} {data}")
                    return
                output = data["output"]
                print(f"Request {i} handled by: {data['worker_id']} "
                      f"({len(output.get('sources', []))} chunks retrieved via {output.get('retrieval', '?')})")
                print(f"Response for request {i}: {output['response']}")
                return

            worker = data.get("worker", "unknown")
            print(f"Request {i} handled by: {worker}")
            print(f"Response for request {i}: {data['response']}")

        except Exception as e:
            print(f"Request {i} failed: {e}")

async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rag", action="store_true", help="send kilotech_rag jobs instead of plain prompts")
    args = parser.parse_args()
    tasks = [send_request(i, args.rag) for i in range(0, 10)]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
