#!/bin/bash
set -e
cd /workspaces/Ada-SI

# Create venvs
python3 -m venv .venv
python3 -m venv .venv-litellm

# Install app dependencies
.venv/bin/pip install -q -r chat/requirements.txt -r tool_runtime/requirements.txt

# Install LiteLLM
.venv-litellm/bin/pip install -q "litellm[proxy]"

# Build frontend
cd chat/frontend && npm ci && npm run build && cd ../..

# Create .env
cat > .env << 'ENVEOF'
LITELLM_MASTER_KEY=sk-ada-local-key
OPENCODE_API_KEY=sk-Dzx12O2e2Aev6AWbdHXIjDTnvG1ciHh9eTXAOPfYMdkrkINP1zLdunmdM0z1q4NH
LITE_MODEL=openai/mimo-v2.5-free
TOOL_CREATOR_MODEL=openai/deepseek-v4-flash-free
LITELLM_URL=http://127.0.0.1:4000
TOOL_RUNTIME_URL=http://127.0.0.1:8090
TOOLS_DIR=chat/custom_tools
VENV_PATH=chat/.tool_runtime_venv
LITE_MODEL_REASONING_EFFORT=
ENVEOF

# Start services
bash start.sh
