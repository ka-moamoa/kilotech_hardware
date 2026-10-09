# Build from the repo root:  docker build -f worker/Dockerfile -t kilotech-worker .
#
# App pipelines are baked in from an optional `plugins` build context: any pip-installable
# project whose pyproject.toml registers `kilotech.pipelines` entry points, e.g.
#   docker build -f worker/Dockerfile --build-context plugins=../kilotech_llm_local -t kilotech-worker .
# Without it the image serves only the built-in pipelines (generate, rag).
FROM scratch AS plugins

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

COPY common/ /src/common/
COPY worker/ /src/worker/
RUN pip install /src/common /src/worker

RUN --mount=type=bind,from=plugins,target=/plugin,rw \
    if [ -f /plugin/pyproject.toml ]; then pip install /plugin; else echo "no plugin pipelines"; fi

WORKDIR /var/lib/kilotech-worker
CMD ["kilotech-worker"]
