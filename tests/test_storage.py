from fastapi.testclient import TestClient

from kilotech_common.protocol import RetrieveRequest
from kilotech_storage.app import create_app
from kilotech_storage.corpus import load_corpus
from kilotech_storage.store import Store


def test_corpus_layout(corpus):
    collections = load_corpus(corpus)
    assert set(collections) == {"hawaiian_chunks", "other"}
    chunks = collections["hawaiian_chunks"]
    assert len(chunks) == 3  # bad JSON and blank lines skipped, "body" accepted
    kalo = chunks[1]
    assert kalo.source == "plants/kalo.jsonl" and kalo.metadata == {"chapter": "kalo", "chunk_id": 1}


def test_retrieve_ranks_and_budgets(storage_config):
    store = Store(storage_config)
    store.build()
    hits = store.retrieve(RetrieveRequest(query="where is kalo taro grown", top_k=2, max_chars=0))
    assert hits[0].text.startswith("Kalo taro") and len(hits) == 2
    only = store.retrieve(RetrieveRequest(query="mullet fishponds", collections=["other"]))
    assert [h.collection for h in only] == ["other"]
    tight = store.retrieve(RetrieveRequest(query="kalo taro", top_k=3, max_chars=50))
    assert sum(len(h.text) for h in tight) <= 50
    # Best hit (45 chars) is kept; the next ones don't fit in the remaining 5 and are skipped.
    assert [h.text[:4] for h in tight] == ["Kalo"]
    # A budget smaller than every chunk still returns the best hit, trimmed.
    [trimmed] = store.retrieve(RetrieveRequest(query="kalo taro", top_k=3, max_chars=10))
    assert trimmed.text == "Kalo taro " and trimmed.metadata["truncated"] is True


def test_embeddings_are_cached(storage_config, tmp_path):
    def snapshot():
        return {p.name: p.stat().st_mtime_ns for p in (tmp_path / "index").iterdir()}

    Store(storage_config).build()
    first = snapshot()
    assert len(first) == 2  # one file per collection
    Store(storage_config).build()  # same corpus: files reused, not rewritten
    assert snapshot() == first


def test_http_api(storage_config):
    with TestClient(create_app(storage_config)) as client:
        client.app.state.store.build()  # don't race the background build
        assert client.get("/healthz").json()["status"] == "ready"
        names = {c["name"]: c for c in client.get("/v1/collections").json()}
        assert names["hawaiian_chunks"]["chunks"] == 3 and names["hawaiian_chunks"]["files"] == 2
        body = client.post("/v1/retrieve", json={"query": "breadfruit soil", "top_k": 1}).json()
        assert body["chunks"][0]["text"].startswith("Breadfruit") and body["embedder"] == "hashing-1024"
        assert client.post("/v1/retrieve", json={"query": "x", "collections": ["nope"]}).status_code == 404
        assert len(client.post("/v1/embed", json={"texts": ["a", "b"]}).json()["embeddings"]) == 2
