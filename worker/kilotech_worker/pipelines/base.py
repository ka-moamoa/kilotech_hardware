"""Pipelines turn a job into an output. The agent picks one by `job.task`.

A pipeline is any object with a `name` and an async `run(job, ctx) -> dict`, built by a
factory called with its config dict (a class taking `config` works). Plugins do not need
to import this package: the job and context are plain duck-typed objects, so app repos
such as kilotech_llm_local can ship pipelines with no dependency on the worker code.

The returned dict becomes the job output; a "metrics" key in it is moved to job metrics.
Raise ValueError for bad input (not retried). Exceptions with `retryable = True`,
ConnectionError, TimeoutError or httpx transport errors are retried on another attempt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..backends import LLMBackend
from ..storage_client import StorageClient


@dataclass
class PipelineContext:
    llm: LLMBackend
    storage: StorageClient | None
    default_model: str | None
    worker_id: str
    labels: dict[str, str] = field(default_factory=dict)

    def model_for(self, job: Any) -> str:
        model = job.model or self.default_model
        if not model:
            raise ValueError("job names no model and this worker has no default_model")
        return model


class Pipeline(Protocol):
    name: str

    async def run(self, job: Any, ctx: PipelineContext) -> dict[str, Any]: ...
