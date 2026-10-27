#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f .env ]] || cp .env.example .env
[[ -x .venv/bin/python ]] || { echo 'Сначала создайте .venv и установите зависимости (README)'; exit 1; }
docker compose up -d --wait db
.venv/bin/python -m scripts.init_db
pids=()
cleanup() { for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM
.venv/bin/python -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8010 --no-access-log & pids+=("$!")
.venv/bin/python -m app.backend.ai.worker & pids+=("$!")
.venv/bin/python -m scripts.scheduler & pids+=("$!")
(cd app/frontend && exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5174) & pids+=("$!")
echo 'Приложение: http://localhost:5174 · Остановка: Ctrl+C'
wait
