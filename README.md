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

### Setting up a machine (script)

After cloning this repo to `~/`, run the setup script as your normal user (not with
`sudo`), giving the machine's role:

```
~/kilotech_hardware/tools/setup_node.sh --role worker   # check everything, fix what is missing
~/kilotech_hardware/tools/setup_node.sh --check         # only report what is missing
```

The role is saved, so later runs don't need `--role`. If no role is given or saved, the
script asks for one. Several roles can share a machine (`--role gateway,storage`). `all`
sets up everything, for the one-machine test cluster or a dev box. Each role gets:

| Role | Repos in `/srv` | Ollama + model | venvs |
| --- | --- | --- | --- |
| gateway | `kilotech_hardware` | no | `kilotech_hardware` |
| storage | `kilotech_hardware`, `kilotech_llm_local` (corpus) | no | `kilotech_hardware` |
| worker | `kilotech_hardware`, `kilotech_llm_local` (plugin) | yes | both |

For the role's needs, the script checks each item below and only does the ones that are
not done yet, so it is safe to re-run:

- installs base packages (git, ssh, curl, python3)
- creates a GitHub deploy key for each repo the role needs (`~/.ssh/<repo>_deploy_ed25519`)
  and a `Host github.com-<repo>` entry in `~/.ssh/config`, then prints the public keys
- installs Docker Engine and the compose plugin, enables the service, and adds you to the
  `docker` group (every role)
- workers only: installs Ollama, starts it, and pulls `gemma4` (`--model` to change)
- clones the role's repos into `/srv` through the deploy keys (or switches an existing
  clone's `origin` to them)
- creates a `.venv` with all dependencies in those `/srv` repos

Add each printed key to its repo on GitHub under **Settings > Deploy keys** (read-only is
enough). The keys are printed early, so you can add them while Docker and Ollama install.
Before cloning, the script waits for you to confirm the keys are added. Run
`tools/setup_node.sh --help` for all options (`--skip`, `--non-interactive`, ...).

The Ollama installed on the host is for the local CLI. The worker containers run their
own Ollama and pull `WORKER_MODELS` themselves.

### Where the repos go on Linux

The script sets this up for you. To do it by hand: on each Linux machine, keep two
copies of the repos:

- **`~/` (your user directory):** your working copy for editing, `git pull`, and running
  tests.
- **`/srv/`:** the deployment copy. The cluster's Docker containers are built and run from
  here, so they do not depend on any one user's home directory.

Workers and storage also need `kilotech_llm_local`. Clone it next to this repo in both
places. The `.env.example` defaults (`../../kilotech_llm_local/...`) assume the two repos
are siblings.

```
# 1. Working copy in your user directory
cd ~
git clone https://github.com/ka-moamoa/kilotech_hardware.git
git clone https://github.com/ka-moamoa/kilotech_llm_local.git    # workers and storage only

# 2. Deployment copy in /srv
sudo git clone https://github.com/ka-moamoa/kilotech_hardware.git /srv/kilotech_hardware
sudo git clone https://github.com/ka-moamoa/kilotech_llm_local.git /srv/kilotech_llm_local   # workers and storage only
sudo chown -R "$USER": /srv/kilotech_hardware /srv/kilotech_llm_local
```

Run every `docker compose` deploy command from `/srv/kilotech_hardware`. To update a node,
`git pull` in `/srv/kilotech_hardware` (and `/srv/kilotech_llm_local`), then run the
`up -d --build` command again.

### Bringing up the nodes

Once the repos are in place on each machine, follow the README in that machine's role
folder:

1. storage: `storage/README.md`
2. gateway: `gateway/README.md`
3. each worker: `worker/README.md` (point `GATEWAY_URL` and `STORAGE_URLS` at the machines above)

Use the same `CLUSTER_TOKEN` everywhere.

## Development

```
pip install -r requirements-dev.txt
pytest          # queue, storage, config, and an in-process end-to-end cluster (no Docker)
```
