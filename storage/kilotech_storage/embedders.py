"""Text embedders. All return L2-normalised float32 rows, so a dot product is cosine similarity."""
from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod

import numpy as np

from kilotech_common.util import import_object


class Embedder(ABC):
    name: str
    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """(len(texts), dim) float32, rows L2-normalised."""


class SentenceTransformerEmbedder(Embedder):
    def __init__(self, model: str = "all-MiniLM-L6-v2", device: str = "cpu", batch_size: int = 64):
        from sentence_transformers import SentenceTransformer  # heavy; only imported when used

        self._model = SentenceTransformer(model, device=device)
        self._batch_size = int(batch_size)
        self.name = f"sentence-transformers/{model}"
        get_dim = (getattr(self._model, "get_embedding_dimension", None)  # sentence-transformers >= 5.2
                   or self._model.get_sentence_embedding_dimension)
        self.dim = get_dim()

    def embed(self, texts: list[str]) -> np.ndarray:
        return self._model.encode(texts, batch_size=self._batch_size, normalize_embeddings=True,
                                  convert_to_numpy=True, show_progress_bar=False).astype(np.float32)


class HashingEmbedder(Embedder):
    """Dependency-free hashed bag-of-words. Keyword-level quality only; meant for tests and
    for bringing a node up before the real model is available."""

    def __init__(self, dim: int = 1024):
        self.dim = int(dim)
        self.name = f"hashing-{self.dim}"

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in re.findall(r"\w+", text.lower()):
                digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
                out[row, int.from_bytes(digest, "little") % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


EMBEDDERS = {
    "sentence-transformers": SentenceTransformerEmbedder,
    "hashing": HashingEmbedder,
}


def build_embedder(config) -> Embedder:
    cls = EMBEDDERS.get(config.type) or import_object(config.type)
    return cls(**config.model_dump(exclude={"type"}))
