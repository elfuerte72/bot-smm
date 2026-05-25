from __future__ import annotations

from fastapi import APIRouter
from loguru import logger

from src.storage.db import get_conn

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Health-check: проверяет, что SQLite-коннект жив (SELECT 1).

    Используется в Dockerfile HEALTHCHECK и в smoke-тестах после деплоя.
    На ошибку открытия БД возвращает db='error' (не 500), чтобы Traefik
    мог отличить «контейнер мёртв» от «БД отвалилась».
    """
    db_status = "ok"
    try:
        async with get_conn() as conn:
            async with conn.execute("SELECT 1") as cur:
                await cur.fetchone()
    except Exception:  # noqa: BLE001
        logger.exception("health: SELECT 1 failed")
        db_status = "error"
    return {"status": "ok", "db": db_status}
