"""The storage node's state: every collection's chunks, embeddings and index.

Embeddings are cached on disk keyed by (collection, embedder, hash of the chunk texts), so
a restart reuses them and only a changed corpus is re-embedded.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from kilotech_common.protocol import Chunk, CollectionInfo, RetrieveRequest

from .config import StorageConfig
from .corpus import ChunkRecord, load_corpus
from .embedders import Embedder, build_embedder
from .index import VectorIndex, build_index

log = logging.getLogger("kilotech.storage")


class UnknownCollection(KeyError):
    pass


@dataclass
class Collection:
    name: str
    chunks: list[ChunkRecord]
    index: VectorIndex

    def info(self) -> CollectionInfo:
        return CollectionInfo(name=self.name, chunks=len(self.chunks),
                              files=len({c.source for c in self.chunks}))


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)


class Store:
    def __init__(self, config: StorageConfig, embedder: Embedder | None = None):
        self.config = config
        self.embedder = embedder
        self.collections: dict[str, Collection] = {}
        self.status = "loading"
        self.error: str | None = None
        self._build_lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return bool(self.collections) or self.status == "ready"

    def build(self) -> None:
        """(Re)load the corpus and indexes. Blocking: run it in a thread. Queries keep
        using the previous collections until the new ones are swapped in."""
        with self._build_lock:
            started = time.time()
            try:
                if self.embedder is None:
                    self.embedder = build_embedder(self.config.embedder)
                corpus = load_corpus(self.config.corpus_dir)
                built = {
                    name: Collection(name, chunks,
                                     build_index(self.config.index, self._embeddings(name, chunks)))
                    for name, chunks in corpus.items()
                }
            except Exception as exc:
                self.status, self.error = "error", repr(exc)
                log.exception("building the index failed")
                return
            self.collections = built
            self.status, self.error = "ready", None
            log.info("indexed %d collection(s), %d chunks in %.1fs with %s", len(built),
                     sum(len(c.chunks) for c in built.values()), time.time() - started,
                     self.embedder.name)

    def _embeddings(self, name: str, chunks: list[ChunkRecord]) -> np.ndarray:
        digest = hashlib.sha256()
        digest.update(self.embedder.name.encode())
        for chunk in chunks:
            digest.update(b"\0" + chunk.text.encode())
        prefix = f"{_slug(name)}--{_slug(self.embedder.name)}--"
        index_dir = Path(self.config.index_dir)
        path = index_dir / f"{prefix}{digest.hexdigest()[:16]}.npy"

        if path.exists():
            cached = np.load(path)
            if cached.shape == (len(chunks), self.embedder.dim):
                log.info("collection %s: loaded cached embeddings", name)
                return cached

        log.info("collection %s: embedding %d chunks...", name, len(chunks))
        embeddings = self.embedder.embed([c.text for c in chunks])
        index_dir.mkdir(parents=True, exist_ok=True)
        for stale in index_dir.glob(f"{prefix}*.npy"):
            stale.unlink()
        tmp = path.with_suffix(".tmp")
        with tmp.open("wb") as f:
            np.save(f, embeddings)
        os.replace(tmp, path)
        return embeddings

    def list_collections(self) -> list[CollectionInfo]:
        return [c.info() for c in self.collections.values()]

    def retrieve(self, req: RetrieveRequest) -> list[Chunk]:
        collections = self.collections  # snapshot: a rebuild may swap it
        names = req.collections or list(collections)
        missing = [n for n in names if n not in collections]
        if missing:
            raise UnknownCollection(f"unknown collection(s): {', '.join(missing)}")
        top_k = req.top_k or self.config.default_top_k
        max_chars = self.config.default_max_chars if req.max_chars is None else req.max_chars

        query = self.embedder.embed([req.query])[0]
        hits: list[tuple[float, Collection, int]] = []
        for name in names:
            ids, scores = collections[name].index.search(query, top_k)
            hits += [(float(s), collections[name], int(i)) for i, s in zip(ids, scores)]
        hits.sort(key=lambda h: h[0], reverse=True)

        results: list[Chunk] = []
        chars = 0
        for score, collection, idx in hits[:top_k]:
            if req.min_score is not None and score < req.min_score:
                break
            chunk = collection.chunks[idx]
            text, metadata = chunk.text, chunk.metadata
            if max_chars and chars + len(text) > max_chars:
                # Skip chunks that don't fit (a smaller, lower-ranked one still may), but never
                # return nothing: most corpus chunks are longer than a typical budget, so the
                # best hit is trimmed to fit instead.
                if results:
                    continue
                text, metadata = text[:max_chars], {**metadata, "truncated": True}
            chars += len(text)
            results.append(Chunk(text=text, score=score, collection=chunk.collection,
                                 source=chunk.source, line=chunk.line, metadata=metadata))
        return results
