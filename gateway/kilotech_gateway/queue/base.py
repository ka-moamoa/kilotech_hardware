"""Job queue interface. The gateway only talks to this, so the in-memory queue can be
swapped for a persistent one (e.g. Redis) without touching the API layer."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from kilotech_common.protocol import Job, JobSpec, WorkerInfo


class QueueFull(Exception):
    pass


class JobNotFound(KeyError):
    pass


class LeaseLost(Exception):
    """The caller no longer holds the job's lease (it expired, was cancelled or finished)."""


class JobQueue(ABC):
    @abstractmethod
    async def submit(self, spec: JobSpec) -> Job:
        """Enqueue a job. Raises QueueFull when at capacity."""

    @abstractmethod
    async def get(self, job_id: str) -> Job | None: ...

    @abstractmethod
    async def claim(self, worker: WorkerInfo, wait_s: float) -> Job | None:
        """Lease the best job `worker` can run, waiting up to `wait_s` for one to arrive."""

    @abstractmethod
    async def heartbeat(self, job_id: str, lease_id: str) -> Job:
        """Extend a lease. Raises LeaseLost / JobNotFound."""

    @abstractmethod
    async def complete(self, job_id: str, lease_id: str, output: dict[str, Any],
                       metrics: dict[str, Any]) -> Job: ...

    @abstractmethod
    async def fail(self, job_id: str, lease_id: str, error: str, retryable: bool,
                   metrics: dict[str, Any]) -> Job:
        """Requeue if retryable and attempts remain, otherwise mark failed."""

    @abstractmethod
    async def cancel(self, job_id: str) -> Job: ...

    @abstractmethod
    async def wait(self, job_id: str, timeout_s: float) -> Job:
        """Return the job once it is terminal, or as it stands after `timeout_s`."""

    @abstractmethod
    async def release_worker(self, worker_id: str, *, count_attempt: bool = True) -> int:
        """Requeue every job leased by a worker that has gone away. Returns the count.
        `count_attempt=False` (graceful deregister: the jobs never ran) refunds the attempt."""

    @abstractmethod
    async def reap(self) -> None:
        """Requeue expired leases and drop old finished jobs. Called periodically."""

    @abstractmethod
    async def stats(self) -> dict[str, Any]: ...
