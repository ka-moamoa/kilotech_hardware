Deployment code for the Kilotech compute cluster, split by node role. Each machine installs
only its own role:

| Folder | Node | What runs there |
| --- | --- | --- |
| `gateway/` | gateway / load balancer (one) | FastAPI job queue that clients submit to and workers pull from |
| `worker/` | worker nodes (many) | Ollama + `kilotech-worker` agent running pipelines (e.g. KiloTech RAG) |
| `storage/` | storage node(s) | RAG corpus + embedding index served over HTTP |
| `common/` | (library) | wire-protocol models and config loading shared by the three |

```
client ──► gateway (queue) ◄── pull ── worker 1..N ──► storage
   ▲         │  result                    │ (Ollama)       (retrieval)
   └─────────┘◄───────────────────────────┘
```

**Design:**

- **Workers pull; the gateway never calls them.** Free workers long-poll for jobs, so
  faster machines naturally take more work. Nodes can be added or removed without
  reconfiguring anything.
- **Workers advertise what they can do.** Each one reports the tasks and models it serves,
  plus labels (arch, cpus, mem_gb, accel). Jobs only go to workers that match, and a job
  can require labels.
- **Lease-based.** A crashed worker's job is retried elsewhere, and a slow one keeps its
  lease by heartbeating.
- **The contract is plain HTTP + JSON** (`common/kilotech_common/protocol.py`). Parts can be
  swapped behind small interfaces:
  - the queue (in-memory now, Redis later)
  - the model backend (Ollama, OpenAI-compatible, echo)
  - pipelines (plugins from app repos)
  - the embedder and vector index

## Protocol (v1)

| Caller | Endpoint | |
| --- | --- | --- |
| client | `POST /v1/jobs` | `{task, model?, input, options?, requirements?, priority?}` → `202 {id}` (429 if the queue is full) |
| client | `GET /v1/jobs/{id}` / `DELETE /v1/jobs/{id}` | status + output + timings / cancel |
| client | `POST /v1/generate?timeout_s=` | submit and wait: 200 done, 502 failed, 504 still running |
| client | `POST /api/generate` (and `/generate`) | Ollama-compatible; used by `client.py` |
| worker | `POST /v1/workers/register`, `/{id}/claim`, `/{id}/deregister` | claim is a long-poll: 200 job or 204 |
| worker | `POST /v1/jobs/{id}/heartbeat`, `/complete`, `/fail` | 409 means the lease was lost |
| ops | `GET /v1/cluster`, `GET /healthz`, `/docs` | workers, queue depth |

Tasks available today: `generate` (`input.prompt`), `rag` (`input.query`), and
`kilotech_rag` (`input.query`, from `kilotech_llm_local`).

## Local test (everything on one machine)

`docker compose up -d --build` starts the gateway, storage, and three worker nodes. The
first start pulls `qwen2.5:3b` and embeds the corpus from `../kilotech_llm_local`. Then:

```
python client.py                                   # load test (Ollama-compatible API)
python tools/ask.py "When should I plant kalo?"    # KiloTech RAG through the cluster
curl localhost:8000/v1/cluster                     # who is registered, queue depth
```

Settings for the local stack come from environment variables or a root `.env`:
`WORKER_MODELS`, `CLUSTER_TOKEN`, `CORPUS_DIR`, `WORKER_PLUGIN_DIR`.

## Deploying to the cluster (Ubuntu, Docker)

Clone this repo on each machine (plus `kilotech_llm_local` on workers and storage), then
follow the README in that machine's role folder:

1. storage: `storage/README.md`
2. gateway: `gateway/README.md`
3. each worker: `worker/README.md` (point `GATEWAY_URL` and `STORAGE_URLS` at the machines above)

Use the same `CLUSTER_TOKEN` everywhere.

## Development

```
pip install -r requirements-dev.txt
pytest          # queue, storage, config, and an in-process end-to-end cluster (no Docker)
```
