import json

import pytest

from kilotech_storage.config import EmbedderConfig, StorageConfig


@pytest.fixture
def corpus(tmp_path):
    """A tiny corpus in the same layout as hawaiian_chunks: collection/book/chapter.jsonl."""
    root = tmp_path / "corpus"
    book = root / "hawaiian_chunks" / "plants"
    book.mkdir(parents=True)
    (book / "kalo.jsonl").write_text("\n".join(json.dumps(o) for o in [
        {"chapter": "kalo", "chunk_id": 1, "text": "Kalo taro is grown in flooded lo'i terraces."},
        {"chapter": "kalo", "chunk_id": 2, "body": "Breadfruit ulu trees need well drained soil."},
    ]) + "\n\nnot json\n", encoding="utf-8")
    (root / "hawaiian_chunks" / "history.jsonl").write_text(
        json.dumps({"text": "King Kalakaua reigned from 1874 to 1891."}) + "\n", encoding="utf-8")
    (root / "other").mkdir()
    (root / "other" / "misc.jsonl").write_text(
        json.dumps({"text": "Fishponds loko i'a raised mullet."}) + "\n", encoding="utf-8")
    return root


@pytest.fixture
def storage_config(corpus, tmp_path):
    return StorageConfig(corpus_dir=str(corpus), index_dir=str(tmp_path / "index"),
                         embedder=EmbedderConfig(type="hashing"))
