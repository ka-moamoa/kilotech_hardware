#!/bin/sh
# One-shot model download into a shared Ollama volume (used by the local all-in-one
# compose, where several Ollama containers share one volume and must not pull at once).
# Real worker nodes don't need this: the agent pulls missing models itself.
set -e

ollama serve >/tmp/ollama.log 2>&1 &
server=$!

until ollama list >/dev/null 2>&1; do sleep 1; done

for model in $PULL_MODELS; do
  echo "pulling $model"
  ollama pull "$model"
done

kill "$server"
