# Build from the repo root:  docker build -f storage/Dockerfile -t kilotech-storage .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/data/cache/hf

# CPU-only torch keeps the image ~1 GB instead of pulling the CUDA wheels.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY common/ /src/common/
COPY storage/ /src/storage/
RUN pip install /src/common "/src/storage[sentence-transformers]"

EXPOSE 8100
VOLUME ["/data/cache"]
# The first start downloads the embedding model and embeds the corpus: allow time.
HEALTHCHECK --interval=15s --timeout=3s --start-period=600s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/healthz', timeout=2)"
CMD ["kilotech-storage"]
