#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/.."
test -f .env || .venv/bin/python scripts/setup.py
docker compose up -d --build
.venv/bin/python -m desktop.main
