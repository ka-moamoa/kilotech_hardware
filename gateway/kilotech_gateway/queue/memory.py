"""In-process job queue. Fast and dependency-free; queued jobs are lost if the gateway
restarts (acceptable for now, a Redis-backed JobQueue can replace it later).

Pending jobs sit in buckets keyed by (task, model, requirements), each a heap ordered by
(-priority, arrival). A claim looks only at bucket heads the worker can serve, so it costs
O(buckets) rather than O(queued jobs). Workers long-poll on a Condition, so nothing spins.
"""
from __future__ import annotations

import asyncio
import heapq
import itertools
import time
from collections import Counter
from typing import Any

from kilotech_common.protocol import Job, JobSpec, JobState, WorkerInfo, new_id

from .base import JobNotFound, JobQueue, LeaseLost, QueueFull

BucketKey = tuple[str, "str | None", tuple[tuple[str, str], ...]]


def _bucket_key(job: Job) -> BucketKey:
    return job.task, job.model, tuple(sorted(job.requirements.items()))


def _serves(worker: WorkerInfo, key: BucketKey) -> bool:
    task, model, requirements = key
    if task not in worker.tasks:
        return False
    if model is not None and model not in worker.models:
        return False
    return all(worker.labels.get(k) == v for k, v in requirements)


class MemoryQueue(JobQueue):
    def __init__(self, *, lease_s: float = 60, max_attempts: int = 3, max_queued: int = 1000,
                 result_ttl_s: float = 3600):
        self.lease_s = lease_s
        self.max_attempts = max_attempts
        self.max_queued = max_queued
        self.result_ttl_s = result_ttl_s

        self._jobs: dict[str, Job] = {}
        self._buckets: dict[BucketKey, list[tuple[int, int, str]]] = {}
        self._arrival: dict[str, int] = {}  # kept across requeues so retries keep their place
        self._done: dict[str, asyncio.Event] = {}
        self._seq = itertools.count()
        self._queued = 0
        self._cond = asyncio.Condition()

    # ------------------------------------------------------------ internals

    def _push(self, job: Job) -> None:
        heap = self._buckets.setdefault(_bucket_key(job), [])
        heapq.heappush(heap, (-job.priority, self._arrival[job.id], job.id))
        self._queued += 1

    def _pop_for(self, worker: WorkerInfo) -> Job | None:
        best: list[tuple[int, int, str]] | None = None
        empty = []
        for key, heap in self._buckets.items():
            # Drop entries for jobs that were cancelled or garbage-collected while queued.
            while heap and getattr(self._jobs.get(heap[0][2]), "state", None) != JobState.QUEUED:
                heapq.heappop(heap)
            if not heap:
                empty.append(key)
            elif _serves(worker, key) and (best is None or heap[0] < best[0]):
                best = heap
        for key in empty:
            del self._buckets[key]
        if best is None:
            return None
        self._queued -= 1
        return self._jobs[heapq.heappop(best)[2]]

    def _leased(self, job_id: str, lease_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        if job.state != JobState.LEASED or job.lease_id != lease_id:
            raise LeaseLost(f"job {job_id} is {job.state.value}")
        return job

    def _finish(self, job: Job, state: JobState, error: str | None = None) -> None:
        job.state = state
        job.finished_at = time.time()
        job.lease_id = None
        job.lease_expires_at = None
        if error is not None:
            job.error = error
        self._done[job.id].set()

    def _requeue_or_fail(self, job: Job, reason: str) -> None:
        if job.attempt < (job.max_attempts or self.max_attempts):
            job.state = JobState.QUEUED
            job.worker_id = None
            job.lease_id = None
            job.lease_expires_at = None
            job.error = reason
            self._push(job)
            self._cond.notify_all()
        else:
            self._finish(job, JobState.FAILED, f"{reason} (after {job.attempt} attempts)")

    # ------------------------------------------------------------ JobQueue

    async def submit(self, spec: JobSpec) -> Job:
        async with self._cond:
            if self._queued >= self.max_queued:
                raise QueueFull(f"{self._queued} jobs already queued")
            job = Job(**spec.model_dump())
            job.max_attempts = job.max_attempts or self.max_attempts
            self._jobs[job.id] = job
            self._done[job.id] = asyncio.Event()
            self._arrival[job.id] = next(self._seq)
            self._push(job)
            self._cond.notify_all()
            return job.model_copy()

    async def get(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        return job.model_copy() if job else None

    async def claim(self, worker: WorkerInfo, wait_s: float) -> Job | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(wait_s, 0)
        async with self._cond:
            while True:
                job = self._pop_for(worker)
                if job is not None:
                    now = time.time()
                    job.state = JobState.LEASED
                    job.attempt += 1
                    job.worker_id = worker.worker_id
                    job.lease_id = new_id()
                    job.leased_at = now
                    job.lease_expires_at = now + self.lease_s
                    return job.model_copy()
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return None
                try:
                    await asyncio.wait_for(self._cond.wait(), remaining)
                except asyncio.TimeoutError:
                    pass

    async def heartbeat(self, job_id: str, lease_id: str) -> Job:
        job = self._leased(job_id, lease_id)
        job.lease_expires_at = time.time() + self.lease_s
        return job.model_copy()

    async def complete(self, job_id: str, lease_id: str, output: dict[str, Any],
                       metrics: dict[str, Any]) -> Job:
        job = self._leased(job_id, lease_id)
        job.output = output
        job.metrics.update(metrics)
        job.error = None
        self._finish(job, JobState.SUCCEEDED)
        return job.model_copy()

    async def fail(self, job_id: str, lease_id: str, error: str, retryable: bool,
                   metrics: dict[str, Any]) -> Job:
        async with self._cond:
            job = self._leased(job_id, lease_id)
            job.metrics.update(metrics)
            if retryable:
                self._requeue_or_fail(job, error)
            else:
                self._finish(job, JobState.FAILED, error)
            return job.model_copy()

    async def cancel(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        if job.state == JobState.QUEUED:
            self._queued -= 1  # its heap entry is dropped lazily by _pop_for
        if not job.state.terminal:
            self._finish(job, JobState.CANCELLED)
        return job.model_copy()

    async def wait(self, job_id: str, timeout_s: float) -> Job:
        done = self._done.get(job_id)
        if done is None:
            raise JobNotFound(job_id)
        try:
            await asyncio.wait_for(done.wait(), timeout_s)
        except asyncio.TimeoutError:
            pass
        return self._jobs[job_id].model_copy()

    async def release_worker(self, worker_id: str, *, count_attempt: bool = True) -> int:
        async with self._cond:
            lost = [j for j in self._jobs.values()
                    if j.state == JobState.LEASED and j.worker_id == worker_id]
            for job in lost:
                if not count_attempt:
                    job.attempt -= 1
                self._requeue_or_fail(job, f"worker {worker_id} went away")
            return len(lost)

    async def reap(self) -> None:
        now = time.time()
        async with self._cond:
            for job in list(self._jobs.values()):
                if job.state == JobState.LEASED and job.lease_expires_at < now:
                    self._requeue_or_fail(job, f"lease expired on worker {job.worker_id}")
                elif job.state.terminal and job.finished_at < now - self.result_ttl_s:
                    del self._jobs[job.id], self._done[job.id], self._arrival[job.id]

    async def stats(self) -> dict[str, Any]:
        by_state = Counter(job.state.value for job in self._jobs.values())
        by_bucket = Counter(
            f"{job.task}/{job.model or '*'}"
            for job in self._jobs.values() if job.state == JobState.QUEUED
        )
        return {"queued": self._queued, "states": dict(by_state), "queued_by_task": dict(by_bucket)}
