# Build from the repo root:  docker build -f worker/Dockerfile -t kilotech-worker .
#
# App pipelines are baked in from an optional `plugins` build context: any pip-installable
# project whose pyproject.toml registers `kilotech.pipelines` entry points, e.g.
#   docker build -f worker/Dockerfile --build-context plugins=../kilotech_llm_local -t kilotech-worker .
# Without it the image serves only the built-in pipelines (generate, rag).
#
# PLUGIN_EXTRAS installs the plugin's optional extras, e.g. `local` for kilotech_llm_local,
# which runs retrieval inside the worker instead of on the storage node (adds CPU torch and
# sentence-transformers, ~2.1 GB image vs ~360 MB):  docker build ... --build-arg PLUGIN_EXTRAS=local
FROM scratch AS plugins

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/var/lib/kilotech-worker/hf

COPY common/ /src/common/
COPY worker/ /src/worker/
RUN pip install /src/common /src/worker

ARG PLUGIN_EXTRAS=
RUN --mount=type=bind,from=plugins,target=/plugin,rw \
    if [ ! -f /plugin/pyproject.toml ]; then echo "no plugin pipelines"; \
    elif [ -n "$PLUGIN_EXTRAS" ]; then \
      pip install --index-url https://download.pytorch.org/whl/cpu torch && \
      pip install "/plugin[$PLUGIN_EXTRAS]"; \
    else pip install /plugin; fi

WORKDIR /var/lib/kilotech-worker
CMD ["kilotech-worker"]
