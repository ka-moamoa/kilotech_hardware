from fastapi import FastAPI
import httpx
import asyncio
import time

app = FastAPI()

workers = {
    "worker1": {"url": "http://worker1:11434", "queue": 0},
    "worker2": {"url": "http://worker2:11434", "queue": 0},
    "worker3": {"url": "http://worker3:11434", "queue": 0},
}

lock = asyncio.Lock()

def get_least_loaded_worker():
    return min(workers.items(), key=lambda x: x[1]["queue"])

@app.post("/generate")
async def generate(request: dict):
    async with lock:
        name, worker = get_least_loaded_worker()
        worker["queue"] += 1
        print(f"{time.time():.2f} -> Assigned to {name}, queue: {worker['queue']}")

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{worker['url']}/api/generate",
                json=request
            )

            result = response.json()
            result['worker'] = name

            return result
    finally:
        async with lock:
            worker["queue"] -= 1