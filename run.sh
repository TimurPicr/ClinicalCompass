#!/bin/sh

set -eu

# Переходим в корень проекта
PROJECT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$PROJECT_DIR"

BACKEND_PID=""

cleanup() {
    if [ -n "$BACKEND_PID" ]; then
        echo ""
        echo "Останавливаем backend..."
        kill "$BACKEND_PID" 2>/dev/null || true
        wait "$BACKEND_PID" 2>/dev/null || true
    fi
}

trap cleanup 0
trap 'exit 130' 2
trap 'exit 143' 15

# 1. Python-окружение
echo "[1/5] Проверяем Python..."

if [ ! -x ".venv/bin/python" ]; then
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
fi

PYTHON="$PROJECT_DIR/.venv/bin/python"

# Do not launch a second application on top of the Docker deployment.
DOCKER_APP_SERVICES=$(docker compose ps --status running --services backend frontend)
if [ -n "$DOCKER_APP_SERVICES" ]; then
    echo "Приложение уже запущено в Docker. Локальная копия не запускается."
    DOCKER_FRONTEND_ADDRESS=$(docker compose port frontend 8080 2>/dev/null || true)
    if [ -n "$DOCKER_FRONTEND_ADDRESS" ]; then
        echo "Откройте: http://localhost:${DOCKER_FRONTEND_ADDRESS##*:}"
    fi
    echo "Для переключения на локальную разработку выполните:"
    echo "  docker compose stop backend frontend"
    echo "  ./run.sh"
    exit 0
fi

# Fail before migrations or background processes if another local app owns a port.
"$PYTHON" - <<'PY'
import socket
import sys

occupied = []
for port in (8000, 5173):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            occupied.append(str(port))
if occupied:
    print("Порты уже заняты: " + ", ".join(occupied))
    print("Остановите ранее запущенные backend/frontend и повторите ./run.sh.")
    sys.exit(1)
PY

# 2. PostgreSQL
echo "[2/5] Запускаем PostgreSQL..."

docker compose up -d --wait db mailpit

echo "Ожидаем готовности базы данных..."

DB_READY=0

for i in $(seq 1 30); do
    if docker compose exec -T db \
        sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
        >/dev/null 2>&1; then
        DB_READY=1
        break
    fi

    sleep 2
done

if [ "$DB_READY" -ne 1 ]; then
    echo "Ошибка: PostgreSQL не запустился"
    exit 1
fi

# 3. Миграции
echo "[3/5] Применяем миграции..."

"$PYTHON" -m alembic upgrade head

# 4. FastAPI
echo "[4/5] Запускаем FastAPI..."

# Settings reads both the shell environment and .env. Preserve configured external
# SMTP; translate Docker's mailpit hostname (or missing config) for a local process.
MAIL_MODE=$("$PYTHON" -c 'from app.backend.core.config import settings; print("local" if settings.smtp_host in ("", "mailpit") else "configured")')

if [ "$MAIL_MODE" = "local" ]; then
    MAILPIT_ADDRESS=$(docker compose port mailpit 1025)
    SMTP_HOST=127.0.0.1 SMTP_PORT="${MAILPIT_ADDRESS##*:}" SMTP_SECURITY=none \
        "$PYTHON" -m uvicorn app.backend.main:app \
        --host 127.0.0.1 --port 8000 --reload &
else
    "$PYTHON" -m uvicorn app.backend.main:app \
        --host 127.0.0.1 --port 8000 --reload &
fi

BACKEND_PID=$!

# 5. React
echo "[5/5] Запускаем React..."

cd "$PROJECT_DIR/app/frontend"

if [ ! -d "node_modules" ]; then
    npm install
fi

echo ""
echo "=================================="
echo "Clinical Compass"
echo ""
echo "Frontend: http://localhost:5173"
echo "Backend:  http://127.0.0.1:8000"
echo "Swagger:  http://127.0.0.1:8000/docs"
echo "=================================="
echo ""
echo "Для остановки нажми Ctrl+C"
echo ""

npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
