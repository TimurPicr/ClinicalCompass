
#!/bin/sh

set -eu

# Переходим в корень проекта
PROJECT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$PROJECT_DIR"

BACKEND_PID=""

cleanup() {
    echo ""
    echo "Останавливаем backend..."

    if [ -n "$BACKEND_PID" ]; then
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

# 2. PostgreSQL
echo "[2/5] Запускаем PostgreSQL..."

docker compose up -d db

echo "Ожидаем готовности базы данных..."

DB_READY=0

for i in $(seq 1 30); do
    if docker compose exec -T db \
        pg_isready -U clinical_user -d clinical_compass \
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

"$PYTHON" -m uvicorn app.backend.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --reload &

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

npm run dev -- --host 127.0.0.1
