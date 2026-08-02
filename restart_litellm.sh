#!/bin/bash
cd /workspaces/Ada-SI
export $(grep -v "^#" .env | xargs)
exec .venv-litellm/bin/litellm --config litellm/config.yaml --port 4000
