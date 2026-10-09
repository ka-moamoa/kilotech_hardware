from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EmbedderConfig(BaseModel):
    """`type` picks the embedder; every other key is passed to its constructor."""

    model_config = ConfigDict(extra="allow")

    type: str = "sentence-transformers"  # or "hashing", or "module:Class"


class StorageConfig(BaseModel):
    """Env prefix KILOTECH_STORAGE_ (e.g. KILOTECH_STORAGE_CORPUS_DIR), YAML via KILOTECH_STORAGE_CONFIG."""

    model_config = ConfigDict(extra="forbid")

    host: str = "0.0.0.0"
    port: int = 8100
    token: str | None = None  # required on /v1/admin/* when set
    log_level: str = "info"

    # Each top-level folder of corpus_dir is a collection; *.jsonl files are found recursively.
    corpus_dir: str = "/data/corpus"
    index_dir: str = "/data/cache/index"  # embedding cache, reused until the corpus changes
    embedder: EmbedderConfig = Field(default_factory=EmbedderConfig)
    index: str = "numpy"  # or "module:Class" implementing kilotech_storage.index.VectorIndex

    default_top_k: int = 6
    default_max_chars: int = 1800
