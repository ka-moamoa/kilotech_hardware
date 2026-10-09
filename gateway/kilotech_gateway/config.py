from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GatewayConfig(BaseModel):
    """Env prefix KILOTECH_GATEWAY_ (e.g. KILOTECH_GATEWAY_LEASE_S=120), YAML via KILOTECH_GATEWAY_CONFIG."""

    model_config = ConfigDict(extra="forbid")

    host: str = "0.0.0.0"
    port: int = 8000
    token: str | None = None  # shared secret required on worker endpoints when set
    log_level: str = "info"

    queue_backend: str = "memory"  # or "module:Class" implementing kilotech_gateway.queue.JobQueue
    max_queued: int = 1000  # submissions beyond this get 429
    max_attempts: int = 3
    lease_s: float = 60  # a worker must heartbeat within this or its job is requeued
    heartbeat_s: float = 15
    claim_wait_s: float = 25  # max long-poll duration for a claim
    worker_ttl_s: float = 90  # forget workers silent for this long
    result_ttl_s: float = 3600  # keep finished jobs this long
    sync_timeout_s: float = 600  # default wait for /v1/generate
    reaper_interval_s: float = 5
