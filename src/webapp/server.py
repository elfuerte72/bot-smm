from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from src.webapp.routes import channel, health, me, posts, reactions

# Папка собранного фронта (Vite build): создаётся multi-stage Dockerfile'ом.
# В dev фронт поднимается отдельным процессом vite на :5173, и static может
# не существовать — в этом случае монтировать его не нужно.
_STATIC_DIR = Path(__file__).resolve().parent / "static"


def build_webapp() -> FastAPI:
    """Собирает FastAPI-приложение.

    Структура:
      * /api/health, /api/me, /api/posts/*, /api/channel/*, /api/posts/reactions/*
      * /assets/* — статические файлы фронта (mount StaticFiles)
      * /* — SPA fallback на index.html (для react-router путей).
    """
    app = FastAPI(
        title="SMM Bot — Mini App API",
        version="0.1.0",
        docs_url=None,  # отключаем /docs в проде: внутренний инструмент, не нужен
        redoc_url=None,
        openapi_url=None,
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(me.router, prefix="/api")
    # Reactions подключаем ДО posts: их пути /posts/reactions/{top,bottom}
    # должны матчиться раньше /posts/{draft_id}, иначе FastAPI ловит 422
    # при попытке распарсить "reactions" как int.
    app.include_router(reactions.router, prefix="/api")
    app.include_router(posts.router, prefix="/api")
    app.include_router(channel.router, prefix="/api")

    if _STATIC_DIR.exists():
        assets_dir = _STATIC_DIR / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        index_path = _STATIC_DIR / "index.html"
        if index_path.exists():
            @app.get("/{full_path:path}", include_in_schema=False)
            async def spa_fallback(full_path: str) -> FileResponse:
                """SPA fallback: любой не-API путь → index.html (react-router)."""
                return FileResponse(index_path)
    else:
        logger.info("webapp static dir не найден ({}), SPA-фолбэк не зарегистрирован", _STATIC_DIR)

    return app
