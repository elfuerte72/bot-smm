from __future__ import annotations

from fastapi import APIRouter, Query

from src.storage import repo
from src.webapp.deps import CurrentUser

router = APIRouter()


# Префикс /posts/reactions/ — это поддерево /posts/. Эти роуты ОБЯЗАНЫ
# подключаться раньше /posts/{draft_id}, иначе FastAPI пытается распарсить
# "reactions" как int draft_id. Регистрируем reactions-router в server.py
# до posts-router'а.


@router.get("/posts/reactions/top")
async def reactions_top(
    user: CurrentUser,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[dict[str, object]]:
    """Топ постов по сумме реакций (DESC)."""
    return await repo.top_reactions(limit=limit)


@router.get("/posts/reactions/bottom")
async def reactions_bottom(
    user: CurrentUser,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[dict[str, object]]:
    """Анти-топ постов по сумме реакций (ASC, только опубликованные ≥ 24ч назад)."""
    return await repo.bottom_reactions(limit=limit)
