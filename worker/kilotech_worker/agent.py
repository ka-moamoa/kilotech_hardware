"""The worker agent: register with the gateway, then keep `concurrency` slots busy by
long-polling for jobs the node can run. A fast node simply pulls more often than a slow
one, which is all the load balancing a heterogeneous cluster needs."""
from __future__ import annotations

import asyncio
import logging
import socket
import time
import uuid
from typing import Any

import httpx

from kilotech_common.protocol import Job, WorkerInfo

from .backends import LLMBackend, build_backend
from .capabilities import detect_labels
from .config import WorkerConfig
from .gateway_client import GatewayClient, LeaseLost, UnknownWorker
from .pipelines import Pipeline, PipelineContext, load_pipelines
from .storage_client import StorageClient

log = logging.getLogger("kilotech.worker")

_MAX_BACKOFF_S = 30


def is_retryable(exc: BaseException) -> bool:
    if getattr(exc, "retryable", False):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.TransportError, ConnectionError, TimeoutError,
                            asyncio.TimeoutError))


class WorkerAgent:
    def __init__(self, config: WorkerConfig, *, backend: LLMBackend | None = None,
                 gateway: GatewayClient | None = None, storage: StorageClient | None = None,
                 pipelines: dict[str, Pipeline] | None = None):
        self.config = config
        self.worker_id = config.id or f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
        self.backend = backend or build_backend(config.backend)
        self.gateway = gateway or GatewayClient(config.gateway_url, token=config.token)
        if storage is None and config.storage_urls:
            storage = StorageClient(config.storage_urls, timeout_s=config.storage_timeout_s)
        self.storage = storage
        self.pipelines = pipelines if pipelines is not None else load_pipelines(
            config.pipelines, config.pipeline_config)

        self.info: WorkerInfo | None = None
        self.ctx: PipelineContext | None = None
        self.heartbeat_s = 15.0
        self.claim_wait_s = 25.0
        self._stop = asyncio.Event()

    # ------------------------------------------------------------ lifecycle

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        try:
            await self._prepare()
            await self._register()
            slots = [asyncio.create_task(self._slot(i)) for i in range(self.config.concurrency)]
            await asyncio.gather(*slots)
        finally:
            await self._shutdown()

    async def _prepare(self) -> None:
        delay = 1.0
        while not await self.backend.health():
            log.info("waiting for %s backend...", self.backend.type)
            await self._sleep(delay)
            delay = min(delay * 2, _MAX_BACKOFF_S)
            if self._stop.is_set():
                return

        available = await self.backend.list_models()
        if self.config.pull_models:
            for model in self.config.models:
                if model not in available:
                    log.info("pulling model %s (this can take a while)", model)
                    await self.backend.pull(model)
        models = self.config.models or available
        missing = sorted(set(models) - set(await self.backend.list_models()))
        if missing:
            log.warning("backend does not have advertised model(s) %s", ", ".join(missing))

        unknown = set(self.config.tasks) - set(self.pipelines)
        if unknown:
            raise ValueError(f"configured tasks have no pipeline: {sorted(unknown)}")
        tasks = self.config.tasks or sorted(self.pipelines)

        labels = {**detect_labels(), **self.config.labels, "backend": self.backend.type}
        self.info = WorkerInfo(worker_id=self.worker_id, tasks=tasks, models=models,
                               labels=labels, concurrency=self.config.concurrency)
        self.ctx = PipelineContext(
            llm=self.backend, storage=self.storage, worker_id=self.worker_id, labels=labels,
            default_model=self.config.default_model or (models[0] if models else None))

    async def _register(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                reply = await self.gateway.register(self.info)
            except httpx.HTTPError as exc:
                log.warning("gateway unreachable (%s); retrying in %.0fs", exc, delay)
                await self._sleep(delay)
                delay = min(delay * 2, _MAX_BACKOFF_S)
                continue
            self.heartbeat_s = reply.heartbeat_s
            self.claim_wait_s = self.config.claim_wait_s or reply.claim_wait_s
            log.info("registered as %s: tasks=%s models=%s", self.worker_id,
                     self.info.tasks, self.info.models)
            return

    async def _shutdown(self) -> None:
        if self.info is not None:
            try:
                await self.gateway.deregister(self.worker_id)
            except httpx.HTTPError:
                pass
        for closable in (self.gateway, self.storage, self.backend):
            if closable is not None:
                await closable.aclose()

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), seconds)
        except asyncio.TimeoutError:
            pass

    async def _until_stopped(self, coro) -> Any:
        """Run `coro` but abandon it (returning None) if the agent is asked to stop."""
        task = asyncio.ensure_future(coro)
        stopper = asyncio.ensure_future(self._stop.wait())
        done, _ = await asyncio.wait({task, stopper}, return_when=asyncio.FIRST_COMPLETED)
        stopper.cancel()
        if task in done:
            return task.result()
        task.cancel()
        return None

    # ------------------------------------------------------------ job loop

    async def _slot(self, slot: int) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                job = await self._until_stopped(self.gateway.claim(self.worker_id, self.claim_wait_s))
            except UnknownWorker:
                log.warning("gateway forgot this worker; registering again")
                await self._register()
                continue
            except httpx.HTTPError as exc:
                log.warning("claim failed (%s); retrying in %.0fs", exc, delay)
                await self._sleep(delay)
                delay = min(delay * 2, _MAX_BACKOFF_S)
                continue
            delay = 1.0
            if job is not None:
                # Jobs already leased are finished even while stopping (graceful drain).
                await self._execute(job, slot)

    async def _execute(self, job: Job, slot: int) -> None:
        log.info("slot %d: running %s job %s (attempt %d)", slot, job.task, job.id, job.attempt)
        started = time.time()
        metrics: dict[str, Any] = {"worker_id": self.worker_id,
                                   "queue_wait_s": round((job.leased_at or started) - job.created_at, 3)}
        pipeline = self.pipelines.get(job.task)
        if pipeline is None:
            await self._report(self.gateway.fail, job, self.worker_id,
                               f"no pipeline for task {job.task!r}", False, metrics)
            return

        lease_lost = asyncio.Event()
        run = asyncio.create_task(pipeline.run(job, self.ctx))
        beat = asyncio.create_task(self._heartbeat(job, run, lease_lost))
        try:
            output = await run
        except asyncio.CancelledError:
            if not lease_lost.is_set():
                raise
            log.warning("job %s: lease lost (cancelled or expired); dropped", job.id)
            return
        except Exception as exc:
            metrics["run_s"] = round(time.time() - started, 3)
            retryable = is_retryable(exc)
            log.warning("job %s failed (%sretryable): %r", job.id, "" if retryable else "not ", exc)
            await self._report(self.gateway.fail, job, self.worker_id,
                               f"{type(exc).__name__}: {exc}", retryable, metrics)
            return
        finally:
            beat.cancel()

        output = dict(output or {})
        metrics.update(output.pop("metrics", None) or {})
        metrics["run_s"] = round(time.time() - started, 3)
        await self._report(self.gateway.complete, job, self.worker_id, output, metrics)
        log.info("job %s done in %.1fs", job.id, metrics["run_s"])

    async def _heartbeat(self, job: Job, run: asyncio.Task, lease_lost: asyncio.Event) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_s)
            try:
                await self.gateway.heartbeat(job, self.worker_id)
            except LeaseLost:
                lease_lost.set()
                run.cancel()
                return
            except httpx.HTTPError as exc:
                log.warning("heartbeat for %s failed: %s", job.id, exc)

    async def _report(self, method, *args) -> None:
        """Deliver a result, retrying briefly if the gateway is momentarily unreachable."""
        for attempt in range(5):
            try:
                await method(*args)
                return
            except LeaseLost:
                log.warning("result discarded: lease no longer held")
                return
            except httpx.HTTPError as exc:
                log.warning("reporting result failed (%s)", exc)
                await asyncio.sleep(2 ** attempt)
        log.error("gave up reporting a result; the gateway will requeue the job")
