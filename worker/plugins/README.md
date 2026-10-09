Default (empty) `plugins` build context for `worker/Dockerfile`.

Point `WORKER_PLUGIN_DIR` at a pip-installable project that registers `kilotech.pipelines`
entry points (such as `kilotech_llm_local`) to bake its pipelines into the worker image.
