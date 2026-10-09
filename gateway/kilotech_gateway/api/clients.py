"""Client-facing endpoints: submit jobs, poll them, or wait for them synchronously."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from kilotech_common.protocol import Job, JobRef, JobSpec, JobState

from ..queue import JobNotFound, QueueFull

router = APIRouter()

# Clients never need the lease id; hiding it keeps them from completing jobs themselves.
_CLIENT_EXCLUDE = {"lease_id"}


def _queue(request: Request):
    return request.app.state.queue


async def _submit(request: Request, spec: JobSpec) -> Job:
    try:
        return await _queue(request).submit(spec)
    except QueueFull as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": "5"}) from exc


async def _submit_and_wait(request: Request, spec: JobSpec, timeout_s: float | None) -> Job:
    job = await _submit(request, spec)
    timeout_s = timeout_s if timeout_s is not None else request.app.state.config.sync_timeout_s
    return await _queue(request).wait(job.id, timeout_s)


@router.post("/v1/jobs", status_code=202, response_model=JobRef)
async def submit_job(spec: JobSpec, request: Request):
    job = await _submit(request, spec)
    return JobRef(id=job.id, state=job.state)


@router.get("/v1/jobs/{job_id}", response_model=Job, response_model_exclude=_CLIENT_EXCLUDE)
async def get_job(job_id: str, request: Request):
    job = await _queue(request).get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return job


@router.delete("/v1/jobs/{job_id}", response_model=JobRef)
async def cancel_job(job_id: str, request: Request):
    try:
        job = await _queue(request).cancel(job_id)
    except JobNotFound as exc:
        raise HTTPException(404, "unknown job") from exc
    return JobRef(id=job.id, state=job.state)


_SYNC_STATUS = {JobState.SUCCEEDED: 200, JobState.FAILED: 502, JobState.CANCELLED: 409}


@router.post("/v1/generate", response_model=Job, response_model_exclude=_CLIENT_EXCLUDE)
async def run_job(spec: JobSpec, request: Request, timeout_s: float | None = None):
    """Submit and wait. 200 succeeded, 502 failed, 409 cancelled, 504 still running
    (the body always carries the job, so the client can keep polling its id)."""
    job = await _submit_and_wait(request, spec, timeout_s)
    status = _SYNC_STATUS.get(job.state, 504)
    return JSONResponse(job.model_dump(mode="json", exclude=_CLIENT_EXCLUDE), status_code=status)


# ---------------------------------------------------------------- Ollama-compatible shim

class OllamaGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    prompt: str = ""
    system: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    stream: bool = False  # accepted but ignored: responses are always returned whole


@router.post("/generate", include_in_schema=False)
@router.post("/api/generate")
async def ollama_generate(body: OllamaGenerateRequest, request: Request):
    """Lets existing Ollama clients (and the old client.py) point at the gateway."""
    spec = JobSpec(
        task="generate",
        model=body.model,
        input={"prompt": body.prompt, "system": body.system},
        options=body.options,
    )
    job = await _submit_and_wait(request, spec, None)
    if job.state != JobState.SUCCEEDED:
        raise HTTPException(_SYNC_STATUS.get(job.state, 504), job.error or job.state.value)
    output = job.output or {}
    return {
        "model": output.get("model", body.model),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "response": output.get("response", ""),
        "done": True,
        "worker": job.worker_id,
        "job_id": job.id,
        **(output.get("metrics") or {}),
    }
