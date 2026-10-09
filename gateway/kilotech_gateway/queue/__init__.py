from kilotech_common.util import import_object

from .base import JobNotFound, JobQueue, LeaseLost, QueueFull
from .memory import MemoryQueue

__all__ = ["JobNotFound", "JobQueue", "LeaseLost", "QueueFull", "MemoryQueue", "build_queue"]

BACKENDS = {"memory": MemoryQueue}


def build_queue(config) -> JobQueue:
    """`queue_backend` is a registered name or a `module:Class` taking the same kwargs."""
    cls = BACKENDS.get(config.queue_backend) or import_object(config.queue_backend)
    return cls(
        lease_s=config.lease_s,
        max_attempts=config.max_attempts,
        max_queued=config.max_queued,
        result_ttl_s=config.result_ttl_s,
    )
