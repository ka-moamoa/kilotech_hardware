"""Wire protocol (v1) spoken between clients, the gateway, workers and storage nodes.

The HTTP API is the contract. These pydantic models are a convenience for the Python
nodes; a node written in any other language only has to send and accept the same JSON.
Add fields with defaults to stay backward compatible; bump PROTOCOL_VERSION otherwise.
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

PROTOCOL_VERSION = "1"
TOKEN_HEADER = "X-Cluster-Token"


def new_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------- jobs (client <-> gateway)

class JobState(str, Enum):
    QUEUED = "queued"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in (JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED)


class JobSpec(BaseModel):
    """What a client submits. `task` names the worker pipeline that should run it."""

    task: str = "generate"
    model: str | None = None  # None: any worker serving `task`, using its default model
    input: dict[str, Any] = Field(default_factory=dict)  # pipeline-specific payload
    options: dict[str, Any] = Field(default_factory=dict)  # model options (temperature, ...)
    requirements: dict[str, str] = Field(default_factory=dict)  # worker label selector
    priority: int = 0  # higher is claimed first
    max_attempts: int | None = None  # None: gateway default


class Job(JobSpec):
    id: str = Field(default_factory=new_id)
    state: JobState = JobState.QUEUED
    attempt: int = 0
    worker_id: str | None = None
    lease_id: str | None = None
    lease_expires_at: float | None = None
    created_at: float = Field(default_factory=time.time)
    leased_at: float | None = None
    finished_at: float | None = None
    output: dict[str, Any] | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class JobRef(BaseModel):
    id: str
    state: JobState


# ---------------------------------------------------------------- workers (worker <-> gateway)

class WorkerInfo(BaseModel):
    """What a worker advertises. The gateway only hands it jobs it can run."""

    worker_id: str
    tasks: list[str]
    models: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    concurrency: int = 1
    protocol: str = PROTOCOL_VERSION


class RegisterResponse(BaseModel):
    worker_id: str
    lease_s: float
    heartbeat_s: float
    claim_wait_s: float


class ClaimRequest(BaseModel):
    wait_s: float = 25.0  # long-poll: how long the gateway may hold the request open


class LeaseRef(BaseModel):
    worker_id: str
    lease_id: str


class HeartbeatResponse(BaseModel):
    lease_expires_at: float


class CompleteRequest(LeaseRef):
    output: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)


class FailRequest(LeaseRef):
    error: str
    retryable: bool = False
    metrics: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------- retrieval (worker <-> storage)

class RetrieveRequest(BaseModel):
    query: str
    collections: list[str] | None = None  # None: search every collection
    top_k: int | None = Field(default=None, ge=1, le=200)  # None: storage default
    max_chars: int | None = Field(default=None, ge=0)  # None: storage default, 0: unlimited
    min_score: float | None = None


class Chunk(BaseModel):
    text: str
    score: float
    collection: str
    source: str  # file path relative to the collection
    line: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrieveResponse(BaseModel):
    chunks: list[Chunk]
    embedder: str


class EmbedRequest(BaseModel):
    texts: list[str]


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    embedder: str
    dim: int


class CollectionInfo(BaseModel):
    name: str
    chunks: int
    files: int
