# Gateway node

The single entry point for clients, and the job queue that workers pull from.

- Jobs wait in buckets keyed by `(task, model, requirements)`, ordered by priority and then
  arrival. A worker's long-poll claim gets the oldest job it is able to run.
- A claimed job is *leased*. The worker must heartbeat it, or the job goes back to the
  queue. It is retried up to `max_attempts` times, then marked failed.
- The queue is in memory for now: queued jobs are lost if the gateway restarts, and
  workers re-register by themselves. A persistent backend such as Redis can replace it by
  implementing `kilotech_gateway.queue.JobQueue` and setting `KILOTECH_GATEWAY_QUEUE_BACKEND=module:Class`.

## Deploy

```
cp gateway/.env.example gateway/.env
docker compose -f gateway/compose.yml up -d --build
curl localhost:8000/v1/cluster            # registered workers + queue depth
```

Interactive API docs are served at `http://<gateway>:8000/docs`. Settings are in
`kilotech_gateway/config.py`; set them as `KILOTECH_GATEWAY_*` env vars or through a YAML file
named by `KILOTECH_GATEWAY_CONFIG`.

## Logging and inspection

```
# Workers connected (id, tasks, models, labels, last_seen) and queue depth
curl -s localhost:8000/v1/cluster | jq

# Just the workers
curl -s localhost:8000/v1/cluster | jq '.workers[] | {worker_id, tasks, models, last_seen}'

# What is in the queue right now: jobs per state, and queued jobs per task/model
curl -s localhost:8000/v1/cluster | jq '.queue'

# Refresh every 2s
watch -n 2 "curl -s localhost:8000/v1/cluster | jq -c '.queue'"

# Gateway logs
docker compose -f gateway/compose.yml logs -f gateway
docker compose -f gateway/compose.yml logs --since 10m gateway
```

A worker whose `last_seen` stops advancing has dropped out and will expire from the registry.
`.queue.states` counts jobs by state (queued, leased, done, failed), and
`.queue.queued_by_task` shows how many are waiting per `task/model`. If you set a cluster
token, add `-H "X-Cluster-Token: $TOKEN"` to calls that need it. When running the root
all-in-one compose, drop `-f gateway/compose.yml` from the log commands.
