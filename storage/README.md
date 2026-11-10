# Storage node

Holds the RAG corpus and serves retrieval to the workers, so workers need neither the
corpus nor an embedding model.

- **Corpus:** every folder under `/data/corpus` is a *collection*, and its `*.jsonl` files
  are read recursively. Each line is `{"text": ...}` (or `"body"`). Other keys are returned
  as metadata. The corpus is mounted read-only, not baked into the image.
- **Embeddings:** computed once with `all-MiniLM-L6-v2` (CPU) and cached in the
  `storage_cache` volume. They are keyed by a hash of the chunk texts, so a restart takes
  seconds and only a changed collection gets re-embedded.
- **Index:** brute-force cosine similarity with numpy. This is exact and fast at this scale.
  Implement `kilotech_storage.index.VectorIndex` to plug in FAISS or a vector DB later.

## Deploy

```
cp storage/.env.example storage/.env      # set CORPUS_DIR
docker compose -f storage/compose.yml up -d --build
curl localhost:8100/healthz               # 503 "loading" until indexed, then 200
```

To scale out, run the same thing on more machines and list them all in the workers'
`STORAGE_URLS`. Workers rotate across them and fail over between them.

## API

| Endpoint | |
| --- | --- |
| `POST /v1/retrieve` | `{query, collections?, top_k?, max_chars?, min_score?}` → `{chunks: [{text, score, collection, source, line, metadata}]}` |
| `GET /v1/collections` | names, chunk and file counts |
| `POST /v1/embed` | `{texts}` → embeddings (same model as the index) |
| `POST /v1/admin/reindex` | re-read the corpus after adding files (needs the cluster token if set) |
| `GET /healthz` | 200 when ready |

Settings live in `kilotech_storage/config.py`. Set them as `KILOTECH_STORAGE_*` env vars (for
example `KILOTECH_STORAGE_EMBEDDER__MODEL`) or through a YAML file named by `KILOTECH_STORAGE_CONFIG`.

## Logging and inspection

```
# Is it ready? Shows "loading" / "ready", any error, and the number of collections
curl -s localhost:8100/healthz | jq

# Collections with chunk and file counts
curl -s localhost:8100/v1/collections | jq

# Try a retrieval by hand
curl -s localhost:8100/v1/retrieve -H 'Content-Type: application/json' \
  -d '{"query": "when to plant kalo", "top_k": 3}' | jq '.chunks[] | {score, collection, source}'

# Re-read the corpus after adding files (add -H "X-Cluster-Token: $TOKEN" if set)
curl -s -X POST localhost:8100/v1/admin/reindex

# Storage logs (indexing and embedding progress)
docker compose -f storage/compose.yml logs -f storage
```
