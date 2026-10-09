"""Corpus loading. Layout: <corpus_dir>/<collection>/**/*.jsonl, one JSON object per line
with the chunk in "text" (or "body"); every other key is kept as metadata. Files placed
directly in corpus_dir belong to the "default" collection."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("kilotech.storage.corpus")


@dataclass
class ChunkRecord:
    text: str
    collection: str
    source: str  # path relative to the collection folder
    line: int
    metadata: dict[str, Any] = field(default_factory=dict)


def load_corpus(root: str | Path) -> dict[str, list[ChunkRecord]]:
    root = Path(root)
    collections: dict[str, list[ChunkRecord]] = {}
    for path in sorted(root.rglob("*.jsonl")):
        rel = path.relative_to(root)
        collection = rel.parts[0] if len(rel.parts) > 1 else "default"
        source = rel.relative_to(collection).as_posix() if len(rel.parts) > 1 else rel.as_posix()
        chunks = collections.setdefault(collection, [])
        with path.open(encoding="utf-8") as f:
            for line_no, line in enumerate(f):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("skipping bad JSON at %s:%d", rel.as_posix(), line_no + 1)
                    continue
                if not isinstance(obj, dict):
                    continue
                text = obj.get("text") or obj.get("body")
                if not isinstance(text, str) or not text.strip():
                    continue
                metadata = {k: v for k, v in obj.items() if k not in ("text", "body")}
                chunks.append(ChunkRecord(text.strip(), collection, source, line_no, metadata))
    return {name: chunks for name, chunks in collections.items() if chunks}
