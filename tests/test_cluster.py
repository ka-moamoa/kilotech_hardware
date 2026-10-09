"""End-to-end, in one process: gateway + storage apps over ASGI transports, and real worker
agents with the echo backend. Exercises the same HTTP protocol the containers use."""
import asyncio
import contextlib

import httpx

from kilotech_gateway.app import create_app as create_gateway
from kilotech_gateway.config import GatewayConfig
from kilotech_storage.app import create_app as create_storage
from kilotech_worker.agent import WorkerAgent
from kilotech_worker.config import WorkerConfig
from kilotech_worker.gateway_client import GatewayClient
from kilotech_worker.storage_client import StorageClient

TOKEN = "s3cret"


class Cluster:
    def __init__(self, storage_config, **gateway_kwargs):
        cfg = dict(token=TOKEN, lease_s=0.3, heartbeat_s=0.05, claim_wait_s=0.5)
        self.gateway = create_gateway(GatewayConfig(**{**cfg, **gateway_kwargs}))
        self.storage = create_storage(storage_config)
        self.storage.state.store.build()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.gateway),
                                        base_url="http://gw", timeout=30)
        self.agents: dict[str, tuple[WorkerAgent, asyncio.Task]] = {}

    async def __aenter__(self):
        self._reaper = asyncio.create_task(self._reap())
        return self

    async def __aexit__(self, *exc):
        for agent, task in self.agents.values():
            agent.stop()
        await asyncio.gather(*(t for _, t in self.agents.values()), return_exceptions=True)
        self._reaper.cancel()
        await self.client.aclose()

    async def _reap(self):  # the lifespan reaper doesn't run under ASGITransport
        while True:
            await asyncio.sleep(0.02)
            await self.gateway.state.queue.reap()

    async def start_worker(self, worker_id, models=("echo",)):
        config = WorkerConfig(id=worker_id, models=list(models), token=TOKEN,
                              backend={"type": "echo", "models": list(models)})
        agent = WorkerAgent(
            config,
            gateway=GatewayClient("http://gw", token=TOKEN, client=httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.gateway), base_url="http://gw")),
            storage=StorageClient(["http://storage"], client=httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.storage))),
        )
        self.agents[worker_id] = (agent, asyncio.create_task(agent.run()))
        for _ in range(100):
            if self.gateway.state.registry.get(worker_id):
                return agent
            await asyncio.sleep(0.01)
        raise AssertionError(f"{worker_id} never registered")

    async def run(self, spec, **params):
        return await self.client.post("/v1/generate", json=spec, params=params)


def test_generate_rag_compat_and_errors(storage_config):
    async def main():
        async with Cluster(storage_config) as c:
            await c.start_worker("w1")

            r = await c.run({"input": {"prompt": "hello"}})
            job = r.json()
            assert r.status_code == 200, job
            assert job["output"]["response"] == "echo: hello" and job["worker_id"] == "w1"
            assert "lease_id" not in job and job["metrics"]["run_s"] >= 0

            r = await c.run({"task": "rag", "input": {"query": "kalo taro lo'i", "top_k": 1}})
            out = r.json()["output"]
            assert "Kalo taro is grown" in out["response"]
            assert out["sources"][0]["source"] == "plants/kalo.jsonl"

            r = await c.client.post("/generate", json={"model": "echo", "prompt": "hi", "stream": False})
            assert r.status_code == 200 and r.json()["response"] == "echo: hi"
            assert r.json()["worker"] == "w1"

            r = await c.run({"input": {}})  # bad input: failed, not retried
            assert r.status_code == 502 and r.json()["attempt"] == 1
            assert "input.prompt" in r.json()["error"]

            r = await c.run({"model": "not-served", "input": {"prompt": "x"}}, timeout_s=0.2)
            assert r.status_code == 504 and r.json()["state"] == "queued"

            r = await c.client.post("/v1/workers/register", json={"worker_id": "x", "tasks": []})
            assert r.status_code == 401  # worker endpoints need the cluster token

            cluster = (await c.client.get("/v1/cluster")).json()
            [w] = cluster["workers"]
            assert set(w["tasks"]) >= {"generate", "rag"} and w["labels"]["backend"] == "echo"
            assert cluster["queue"]["queued"] == 1

    asyncio.run(main())


def test_jobs_route_by_model_and_heartbeats_keep_long_jobs(storage_config):
    async def main():
        async with Cluster(storage_config) as c:
            await c.start_worker("small", models=["m-small"])
            await c.start_worker("big", models=["m-big"])
            # delay (0.8s) is longer than the lease (0.3s): only heartbeats keep it alive.
            slow = c.run({"model": "m-big", "input": {"prompt": "a"}, "options": {"delay_s": 0.8}})
            fast = c.run({"model": "m-small", "input": {"prompt": "b"}})
            r_slow, r_fast = await asyncio.gather(slow, fast)
            assert r_slow.json()["worker_id"] == "big" and r_slow.json()["attempt"] == 1
            assert r_fast.json()["worker_id"] == "small"

    asyncio.run(main())


def test_worker_dying_mid_job_is_retried_elsewhere(storage_config):
    async def main():
        async with Cluster(storage_config) as c:
            await c.start_worker("doomed")
            pending = asyncio.create_task(c.run({"input": {"prompt": "x"}, "options": {"delay_s": 0.5}}))
            queue = c.gateway.state.queue
            for _ in range(100):
                if (await queue.stats())["states"].get("leased"):
                    break
                await asyncio.sleep(0.01)
            _, task = c.agents.pop("doomed")
            task.cancel()  # crash mid-job
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await c.start_worker("survivor")
            job = (await pending).json()
            assert job["state"] == "succeeded" and job["worker_id"] == "survivor"
            # Cancelling the agent still lets it deregister, which requeues without using an
            # attempt. (A hard kill with no deregister is caught by lease expiry and counts.)
            assert job["attempt"] == 1
            assert job["error"] is None

    asyncio.run(main())
