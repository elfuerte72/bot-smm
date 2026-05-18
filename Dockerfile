FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# uv для управления зависимостями (быстрее pip)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Сначала зависимости (для кеша слоёв)
COPY pyproject.toml ./
RUN uv pip install --system --no-cache .

# Затем код
COPY src ./src

# Не-root пользователь
RUN groupadd -g 1000 app && useradd -u 1000 -g app -m app \
    && mkdir -p /data && chown -R app:app /data /app
USER app

ENV DB_PATH=/data/smm.db
VOLUME ["/data"]

CMD ["python", "-m", "src.main"]
