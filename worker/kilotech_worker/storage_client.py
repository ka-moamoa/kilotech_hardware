from __future__ import annotations

import itertools
from typing import Any

import httpx


class StorageUnavailable(Exception):
    retryable = True


class StorageClient:
    """Retrieval over one or more storage nodes. Requests rotate across the nodes and fail
    over to the next one, so storage can be replicated just by listing more URLs."""

    def __init__(self, urls: list[str], *, timeout_s: float = 30,
                 client: httpx.AsyncClient | None = None):
        if not urls:
            raise ValueError("StorageClient needs at least one URL")
        self.urls = [u.rstrip("/") for u in urls]
        self._start = itertools.cycle(range(len(self.urls)))
        self._http = client or httpx.AsyncClient(timeout=timeout_s)

    async def retrieve(self, query: str, *, collections: list[str] | None = None,
                       top_k: int | None = None, max_chars: int | None = None,
                       min_score: float | None = None) -> list[dict[str, Any]]:
        """Return chunk dicts: text, score, collection, source, line, metadata."""
        body = {"query": query, "collections": collections, "top_k": top_k,
                "max_chars": max_chars, "min_score": min_score}
        start = next(self._start)
        errors = []
        for url in self.urls[start:] + self.urls[:start]:
            try:
                response = await self._http.post(f"{url}/v1/retrieve", json=body)
            except httpx.TransportError as exc:
                errors.append(f"{url}: {exc!r}")
                continue
            if response.status_code == 404:
                raise ValueError(response.json().get("detail", "unknown collection"))
            if response.status_code >= 500:
                errors.append(f"{url}: HTTP {response.status_code}")
                continue
            response.raise_for_status()
            return response.json()["chunks"]
        raise StorageUnavailable("no storage node answered: " + "; ".join(errors))

    async def aclose(self) -> None:
        await self._http.aclose()
