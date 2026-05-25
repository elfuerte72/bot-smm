# === STAGE 1: build React Mini App ===
FROM node:20-alpine AS frontend-build

WORKDIR /build

# Сначала только манифесты — для кеша слоя npm ci.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund --prefer-offline

# Потом исходники и сборка.
COPY frontend/ ./
RUN npm run build

# === STAGE 2: build Python virtualenv with uv ===
FROM python:3.12-slim AS python-deps

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Ставим только зависимости (без проекта) — слой инвалидируется лишь при
# изменении pyproject.toml/uv.lock, а не при правках кода.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# === STAGE 3: runtime ===
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/smm.db \
    WEBAPP_HOST=0.0.0.0 \
    WEBAPP_PORT=8000 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Готовый venv (из python-deps).
COPY --from=python-deps /app/.venv /app/.venv

# Python-код приложения.
COPY src ./src

# Собранный React-бандл → FastAPI раздаёт как SPA.
COPY --from=frontend-build /build/dist ./src/webapp/static

# Не-root.
RUN groupadd -g 1000 app && useradd -u 1000 -g app -m app \
    && mkdir -p /data && chown -R app:app /data /app
USER app

VOLUME ["/data"]
EXPOSE 8000

# Healthcheck дёргает /api/health — проверяет, что uvicorn слушает и БД жива.
# urllib — stdlib, без curl/wget в slim-образе.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request, sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)" \
    || exit 1

CMD ["python", "-m", "src.main"]
