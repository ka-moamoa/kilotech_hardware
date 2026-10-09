from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/v1/cluster")
async def cluster(request: Request):
    state = request.app.state
    return {
        "workers": [record.to_dict() for record in state.registry.all()],
        "queue": await state.queue.stats(),
    }
