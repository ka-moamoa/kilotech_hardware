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
