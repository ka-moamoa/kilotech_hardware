import asyncio
import httpx
import time

API_URL = "http://localhost:8000/generate"

async def send_request(i):
    await asyncio.sleep(i * 10)
    print(f"{time.time():.2f} -> Sending request {i}")
    payload = {
        "model": "qwen2.5:3b",
        "prompt": f"Hello, #{i}",
        "stream": False
    }

    if i == 0:
        payload["prompt"] = "Write me an essay of at least 1500 words about the history of Georgia Tech."

    async with httpx.AsyncClient(timeout=300) as client:
        try:
            response = await client.post(API_URL, json=payload)
            data = response.json()

            worker = data.get("worker", "unknown")
            print(f"Request {i} handled by: {worker}")
            print(f"Response for request {i}: {data['response']}")

        except Exception as e:
            print(f"Request {i} failed: {e}")

async def main():
    tasks = [send_request(i) for i in range(0, 10)]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())