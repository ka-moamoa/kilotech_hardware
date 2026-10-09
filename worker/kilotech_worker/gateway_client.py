from __future__ import annotations

from typing import Any

import httpx

from kilotech_common.protocol import (
    TOKEN_HEADER, ClaimRequest, CompleteRequest, FailRequest, Job, LeaseRef, RegisterResponse,
    WorkerInfo,
)


class UnknownWorker(Exception):
    """The gateway does not know this worker (it restarted or evicted us): re-register."""


class LeaseLost(Exception):
    """The job was requeued, cancelled or finished elsewhere; drop the work."""


class GatewayClient:
    def __init__(self, base_url: str, *, token: str | None = None,
                 client: httpx.AsyncClient | None = None):
        headers = {TOKEN_HEADER: token} if token else {}
        self._http = client or httpx.AsyncClient(base_url=base_url, timeout=30)
        self._http.headers.update(headers)

    async def _post(self, path: str, body: Any, **kwargs) -> httpx.Response:
        payload = body.model_dump(mode="json") if hasattr(body, "model_dump") else body
        return await self._http.post(path, json=payload, **kwargs)

    async def register(self, info: WorkerInfo) -> RegisterResponse:
        response = await self._post("/v1/workers/register", info)
        response.raise_for_status()
        return RegisterResponse.model_validate(response.json())

    async def claim(self, worker_id: str, wait_s: float) -> Job | None:
        response = await self._post(f"/v1/workers/{worker_id}/claim", ClaimRequest(wait_s=wait_s),
                                    timeout=wait_s + 15)
        if response.status_code == 404:
            raise UnknownWorker(worker_id)
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return Job.model_validate(response.json())

    async def _lease_call(self, path: str, body: Any) -> dict:
        response = await self._post(path, body)
        if response.status_code in (404, 409):
            raise LeaseLost(response.text)
        response.raise_for_status()
        return response.json()

    async def heartbeat(self, job: Job, worker_id: str) -> None:
        await self._lease_call(f"/v1/jobs/{job.id}/heartbeat",
                               LeaseRef(worker_id=worker_id, lease_id=job.lease_id))

    async def complete(self, job: Job, worker_id: str, output: dict, metrics: dict) -> None:
        await self._lease_call(f"/v1/jobs/{job.id}/complete", CompleteRequest(
            worker_id=worker_id, lease_id=job.lease_id, output=output, metrics=metrics))

    async def fail(self, job: Job, worker_id: str, error: str, retryable: bool,
                   metrics: dict) -> None:
        await self._lease_call(f"/v1/jobs/{job.id}/fail", FailRequest(
            worker_id=worker_id, lease_id=job.lease_id, error=error, retryable=retryable,
            metrics=metrics))

    async def deregister(self, worker_id: str) -> None:
        response = await self._post(f"/v1/workers/{worker_id}/deregister", {})
        response.raise_for_status()

    async def aclose(self) -> None:
        await self._http.aclose()
