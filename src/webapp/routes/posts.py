from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from src.storage import repo
from src.webapp.deps import CurrentUser

router = APIRouter()


# /posts/stats и /posts/reactions/* должны быть зарегистрированы ДО
# /posts/{draft_id}, иначе FastAPI пытается распарсить "stats"/"reactions"
# как int draft_id и возвращает 422. В рамках одного router'а FastAPI
# матчит по порядку объявления — поэтому объявляем строгие пути сверху.


@router.get("/posts/stats")
async def get_posts_stats(user: CurrentUser) -> dict[str, int]:
    """Counts по статусам drafts + total."""
    return await repo.posts_stats()


@router.get("/posts")
async def list_posts(
    user: CurrentUser,
    status: str | None = Query(default=None, pattern="^(draft|publishing|published|rejected)$"),
    period: str = Query(default="all", pattern="^(24h|7d|30d|all)$"),
    search: str | None = Query(default=None, max_length=200),
    offset: int = Query(default=0, ge=0, le=10_000),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    """Постраничный список. Все фильтры — опциональные.

    Параметры валидируются на уровне сигнатуры: неизвестный status/period
    отвергается с 422 от pydantic. search ограничен 200 символами,
    pagination — limit 1..100, offset 0..10000 (защита от подбора).
    """
    items, total = await repo.list_posts(
        status=status,
        period=period,
        search=search,
        offset=offset,
        limit=limit,
    )
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/posts/{draft_id}")
async def get_post(user: CurrentUser, draft_id: int) -> dict[str, object]:
    """Карточка поста с timeline и реакциями."""
    detail = await repo.get_post_detail(draft_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "draft not found")
    return detail
