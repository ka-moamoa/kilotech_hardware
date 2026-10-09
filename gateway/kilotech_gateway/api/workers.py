"""Worker-facing endpoints: register, long-poll for jobs, heartbeat, report results.

Workers always dial the gateway, never the other way round, so worker nodes need no
open ports and can sit anywhere the gateway is reachable from.
"""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from kilotech_common.protocol import (
    ClaimRequest, CompleteRequest, FailRequest, HeartbeatResponse, JobRef, LeaseRef,
    RegisterResponse, TOKEN_HEADER, WorkerInfo,
)

from ..queue import JobNotFound, LeaseLost


def require_token(request: Request, token: str | None = Header(default=None, alias=TOKEN_HEADER)):
    expected = request.app.state.config.token
    if expected and not hmac.compare_digest(token or "", expected):
        raise HTTPException(401, "bad or missing cluster token")


router = APIRouter(prefix="/v1", dependencies=[Depends(require_token)])


@router.post("/workers/register", response_model=RegisterResponse)
async def register(info: WorkerInfo, request: Request):
    state = request.app.state
    state.registry.register(info)
    cfg = state.config
    return RegisterResponse(worker_id=info.worker_id, lease_s=cfg.lease_s,
                            heartbeat_s=cfg.heartbeat_s, claim_wait_s=cfg.claim_wait_s)


@router.post("/workers/{worker_id}/claim")
async def claim(worker_id: str, body: ClaimRequest, request: Request):
    state = request.app.state
    record = state.registry.get(worker_id)
    if record is None:
        # Evicted, or the gateway restarted: the worker should register again.
        raise HTTPException(404, "unknown worker")
    state.registry.touch(worker_id)
    job = await state.queue.claim(record.info, min(body.wait_s, state.config.claim_wait_s))
    state.registry.touch(worker_id)
    if job is None:
        return Response(status_code=204)
    return job


@router.post("/workers/{worker_id}/deregister")
async def deregister(worker_id: str, request: Request):
    state = request.app.state
    state.registry.remove(worker_id)
    # A draining worker finishes what it started, so anything still leased to it here was
    # claimed while it was shutting down and never ran: requeue it without using an attempt.
    return {"requeued": await state.queue.release_worker(worker_id, count_attempt=False)}


def _lease_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, JobNotFound):
        return HTTPException(404, "unknown job")
    return HTTPException(409, str(exc))


@router.post("/jobs/{job_id}/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(job_id: str, ref: LeaseRef, request: Request):
    state = request.app.state
    state.registry.touch(ref.worker_id)
    try:
        job = await state.queue.heartbeat(job_id, ref.lease_id)
    except (JobNotFound, LeaseLost) as exc:
        raise _lease_errors(exc) from exc
    return HeartbeatResponse(lease_expires_at=job.lease_expires_at)


@router.post("/jobs/{job_id}/complete", response_model=JobRef)
async def complete(job_id: str, body: CompleteRequest, request: Request):
    state = request.app.state
    state.registry.touch(body.worker_id)
    try:
        job = await state.queue.complete(job_id, body.lease_id, body.output, body.metrics)
    except (JobNotFound, LeaseLost) as exc:
        raise _lease_errors(exc) from exc
    return JobRef(id=job.id, state=job.state)


@router.post("/jobs/{job_id}/fail", response_model=JobRef)
async def fail(job_id: str, body: FailRequest, request: Request):
    state = request.app.state
    state.registry.touch(body.worker_id)
    try:
        job = await state.queue.fail(job_id, body.lease_id, body.error, body.retryable, body.metrics)
    except (JobNotFound, LeaseLost) as exc:
        raise _lease_errors(exc) from exc
    return JobRef(id=job.id, state=job.state)
