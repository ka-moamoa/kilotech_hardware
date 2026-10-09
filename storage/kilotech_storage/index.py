"""Vector indexes. Brute force is exact and fast enough for tens of thousands of chunks;
swap in FAISS / an external vector DB behind the same interface when the corpus grows."""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from kilotech_common.util import import_object


class VectorIndex(ABC):
    @abstractmethod
    def __init__(self, embeddings: np.ndarray): ...

    @abstractmethod
    def search(self, query: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
        """Top-k (ids, scores), best first."""


class NumpyIndex(VectorIndex):
    def __init__(self, embeddings: np.ndarray):
        self._emb = embeddings

    def search(self, query: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
        k = min(k, len(self._emb))
        if k <= 0:
            return np.empty(0, dtype=int), np.empty(0, dtype=np.float32)
        scores = self._emb @ query
        ids = np.argpartition(-scores, k - 1)[:k]
        ids = ids[np.argsort(-scores[ids])]
        return ids, scores[ids]


INDEXES = {"numpy": NumpyIndex}


def build_index(kind: str, embeddings: np.ndarray) -> VectorIndex:
    cls = INDEXES.get(kind) or import_object(kind)
    return cls(embeddings)
