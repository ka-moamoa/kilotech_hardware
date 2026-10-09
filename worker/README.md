# Worker node

An Ollama model server plus `kilotech-worker`, an agent that **pulls** jobs from the gateway.
The agent only makes outbound connections, so a worker node needs no open ports.

On startup the agent:

1. waits for the model server
2. pulls any missing `WORKER_MODELS`
3. registers the tasks (pipelines) and models it serves, plus auto-detected labels (arch, cpus, mem_gb, accel)

It then keeps `WORKER_CONCURRENCY` long-polls open. The gateway only hands it jobs it can
run. While a job runs, the agent heartbeats its lease. If the node dies, the lease expires
and the job is retried on another node. On `docker stop` the agent finishes in-flight jobs
first.

## Deploy

```
cp worker/.env.example worker/.env      # set GATEWAY_URL, STORAGE_URLS, WORKER_MODELS
docker compose -f worker/compose.yml up -d --build
```

## Extending

- **Pipelines** (what a job *does*): built-ins are `generate` (prompt → text) and `rag`
  (generic retrieve + template). App pipelines live in their own repos and register a
  `kilotech.pipelines` entry point. For example, `kilotech_llm_local` provides `kilotech_rag`.
  `WORKER_PLUGIN_DIR` bakes such a project into the image at build time. A pipeline is any
  object with `name` and `async run(job, ctx) -> dict`; see `kilotech_worker/pipelines/base.py`.
- **Backends** (what serves the model): `ollama`, `openai` (any OpenAI-compatible server:
  vLLM, llama.cpp, LM Studio, ...) and `echo` (a fake model for tests). Select one with
  `KILOTECH_WORKER_BACKEND__TYPE`, or `module:Class` for your own `LLMBackend`.

All settings are in `kilotech_worker/config.py`. Set them as `KILOTECH_WORKER_*` env vars (`__`
for nested keys) or through a YAML file named by `KILOTECH_WORKER_CONFIG`.

`ollama/pull_models.sh` is only used by the root all-in-one compose, where three Ollama
containers share one model volume.
