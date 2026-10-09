# Build from the repo root:  docker build -f gateway/Dockerfile -t kilotech-gateway .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

COPY common/ /src/common/
COPY gateway/ /src/gateway/
RUN pip install /src/common /src/gateway

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["kilotech-gateway"]
