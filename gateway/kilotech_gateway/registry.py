"""Live workers and what they can do. Workers are never configured on the gateway: they
register themselves and are evicted when they stop calling in."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from kilotech_common.protocol import WorkerInfo


@dataclass
class WorkerRecord:
    info: WorkerInfo
    registered_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            **self.info.model_dump(),
            "registered_at": self.registered_at,
            "last_seen": self.last_seen,
        }


class WorkerRegistry:
    def __init__(self, ttl_s: float = 90):
        self.ttl_s = ttl_s
        self._workers: dict[str, WorkerRecord] = {}

    def register(self, info: WorkerInfo) -> WorkerRecord:
        record = WorkerRecord(info)
        self._workers[info.worker_id] = record
        return record

    def get(self, worker_id: str) -> WorkerRecord | None:
        return self._workers.get(worker_id)

    def touch(self, worker_id: str) -> None:
        record = self._workers.get(worker_id)
        if record is not None:
            record.last_seen = time.time()

    def remove(self, worker_id: str) -> None:
        self._workers.pop(worker_id, None)

    def pop_expired(self) -> list[str]:
        cutoff = time.time() - self.ttl_s
        expired = [wid for wid, rec in self._workers.items() if rec.last_seen < cutoff]
        for wid in expired:
            del self._workers[wid]
        return expired

    def all(self) -> list[WorkerRecord]:
        return list(self._workers.values())
