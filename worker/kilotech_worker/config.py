from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kilotech_common.config import StrList


class BackendConfig(BaseModel):
    """`type` picks the backend; every other key is passed to its constructor."""

    model_config = ConfigDict(extra="allow")

    type: str = "ollama"  # registered name or "module:Class"


class WorkerConfig(BaseModel):
    """Env prefix KILOTECH_WORKER_ (e.g. KILOTECH_WORKER_BACKEND__URL), YAML via KILOTECH_WORKER_CONFIG."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = None  # default: <hostname>-<random>
    gateway_url: str = "http://localhost:8000"
    token: str | None = None
    log_level: str = "info"

    concurrency: int = Field(default=1, ge=1)  # jobs run in parallel on this node
    labels: dict[str, str] = Field(default_factory=dict)  # merged over auto-detected labels

    backend: BackendConfig = Field(default_factory=BackendConfig)
    models: StrList = Field(default_factory=list)  # advertised; empty: whatever the backend has
    default_model: str | None = None  # for jobs that name no model; default: first of models
    pull_models: bool = False  # ask the backend to download missing `models` at startup

    tasks: StrList = Field(default_factory=list)  # advertised; empty: every loaded pipeline
    pipelines: StrList = Field(default_factory=list)  # extra "module:attr" or "name=module:attr"
    pipeline_config: dict[str, dict[str, Any]] = Field(default_factory=dict)  # per pipeline

    storage_urls: StrList = Field(default_factory=list)
    storage_timeout_s: float = 30

    claim_wait_s: float | None = None  # default: what the gateway announces
