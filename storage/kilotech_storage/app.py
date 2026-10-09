from __future__ import annotations

import asyncio
import hmac
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from kilotech_common import __version__
from kilotech_common.protocol import (
    TOKEN_HEADER, CollectionInfo, EmbedRequest, EmbedResponse, RetrieveRequest, RetrieveResponse,
)

from .config import StorageConfig
from .embedders import Embedder
from .store import Store, UnknownCollection


def _store(request: Request) -> Store:
    return request.app.state.store


def _ready_store(request: Request) -> Store:
    store = _store(request)
    if not store.ready:
        raise HTTPException(503, f"index not ready ({store.status})", headers={"Retry-After": "10"})
    return store


def _require_token(request: Request, token: str | None = Header(default=None, alias=TOKEN_HEADER)):
    expected = request.app.state.config.token
    if expected and not hmac.compare_digest(token or "", expected):
        raise HTTPException(401, "bad or missing cluster token")


def create_app(config: StorageConfig | None = None, embedder: Embedder | None = None) -> FastAPI:
    config = config or StorageConfig()
    store = Store(config, embedder)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Build in a thread so /healthz answers (503 "loading") while embeddings compute.
        task = asyncio.create_task(asyncio.to_thread(store.build))
        yield
        task.cancel()

    app = FastAPI(title="Kilotech storage", version=__version__, lifespan=lifespan)
    app.state.config = config
    app.state.store = store

    @app.get("/healthz")
    async def healthz():
        body = {"status": store.status, "error": store.error,
                "collections": len(store.collections)}
        return JSONResponse(body, status_code=200 if store.ready else 503)

    @app.get("/v1/collections", response_model=list[CollectionInfo])
    async def collections(s: Store = Depends(_ready_store)):
        return s.list_collections()

    @app.post("/v1/retrieve", response_model=RetrieveResponse)
    async def retrieve(req: RetrieveRequest, s: Store = Depends(_ready_store)):
        try:
            chunks = await asyncio.to_thread(s.retrieve, req)
        except UnknownCollection as exc:
            raise HTTPException(404, str(exc.args[0])) from exc
        return RetrieveResponse(chunks=chunks, embedder=s.embedder.name)

    @app.post("/v1/embed", response_model=EmbedResponse)
    async def embed(req: EmbedRequest, s: Store = Depends(_ready_store)):
        vectors = await asyncio.to_thread(s.embedder.embed, req.texts)
        return EmbedResponse(embeddings=vectors.tolist(), embedder=s.embedder.name, dim=s.embedder.dim)

    @app.post("/v1/admin/reindex", status_code=202, dependencies=[Depends(_require_token)])
    async def reindex():
        """Re-read the corpus (e.g. after copying in new files). Only changed collections
        are re-embedded; queries keep being served from the old index meanwhile."""
        asyncio.create_task(asyncio.to_thread(store.build))
        return {"status": "reindexing"}

    return app
