#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/.."
.venv/bin/python -m PyInstaller --noconfirm --windowed --name OnlineDean --paths . --add-data 'web/cap.svg:web' --add-data 'web/brand.svg:web' --add-data 'web/icons.svg:web' desktop/main.py
printf 'Desktop build: dist/OnlineDean.app\n'
