from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from kilotech_common import __version__

from .api import admin, clients, workers
from .config import GatewayConfig
from .queue import build_queue
from .registry import WorkerRegistry

log = logging.getLogger("kilotech.gateway")


async def _reaper(app: FastAPI) -> None:
    state = app.state
    while True:
        await asyncio.sleep(state.config.reaper_interval_s)
        try:
            for worker_id in state.registry.pop_expired():
                requeued = await state.queue.release_worker(worker_id)
                log.warning("worker %s timed out; requeued %d job(s)", worker_id, requeued)
            await state.queue.reap()
        except Exception:
            log.exception("reaper pass failed")


def create_app(config: GatewayConfig | None = None) -> FastAPI:
    config = config or GatewayConfig()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(_reaper(app))
        yield
        task.cancel()

    app = FastAPI(title="Kilotech gateway", version=__version__, lifespan=lifespan)
    app.state.config = config
    app.state.queue = build_queue(config)
    app.state.registry = WorkerRegistry(config.worker_ttl_s)
    app.include_router(admin.router)
    app.include_router(clients.router)
    app.include_router(workers.router)
    return app
