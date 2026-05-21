FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# uv для управления зависимостями (быстрее pip)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Сначала зависимости (для кеша слоёв). --frozen → ставим строго из uv.lock,
# отказ если lockfile не сходится с pyproject. --no-dev → без ruff и т.п.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Затем код
COPY src ./src
RUN uv sync --frozen --no-dev

# Не-root пользователь
RUN groupadd -g 1000 app && useradd -u 1000 -g app -m app \
    && mkdir -p /data && chown -R app:app /data /app
USER app

ENV DB_PATH=/data/smm.db \
    PATH="/app/.venv/bin:$PATH"
VOLUME ["/data"]

# Лёгкий healthcheck: проверяем, что SQLite-файл доступен и читается.
# init_db создаёт его при старте, так что после start-period (30s) файл должен
# быть на месте. Покрывает кейс «контейнер живёт, но volume отвалился /
# процесс висит без доступа к БД».
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os, sqlite3; sqlite3.connect(os.environ.get('DB_PATH','/data/smm.db')).execute('SELECT 1').close()" || exit 1

CMD ["python", "-m", "src.main"]
