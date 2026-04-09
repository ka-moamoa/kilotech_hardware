#!/bin/sh
# start_worker.sh

# Start Ollama server in the background
ollama serve &

# Give server a few seconds to start
sleep 5

# Pull any models needed into the shared volume
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b

# Keep the container running
wait