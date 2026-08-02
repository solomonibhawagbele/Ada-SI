#!/bin/bash
cd /workspaces/Ada-SI
export $(grep -v "^#" .env | xargs)
cd chat
exec ../.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8080
