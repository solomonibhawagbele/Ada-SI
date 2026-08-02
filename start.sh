#!/bin/bash
set -e
cd /workspaces/Ada-SI

# Load env vars
export $(grep -v "^#" .env | xargs)

pkill -f litellm 2>/dev/null || true
pkill -f "uvicorn" 2>/dev/null || true
pkill -f "ollama serve" 2>/dev/null || true
sleep 1

ollama serve &>/dev/null &
sleep 2

.venv-litellm/bin/litellm --config litellm/config.yaml --port 4000 &>/tmp/litellm.log &
sleep 3

cd tool_runtime
../.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8090 &>/tmp/tool-runtime.log &
sleep 1

cd /workspaces/Ada-SI/chat
../.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8080 &>/tmp/chat.log &
sleep 3

echo "=== Services ==="
echo "Chat: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/)"
echo "LiteLLM: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:4000/health)"
echo "ToolRT: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/health)"
