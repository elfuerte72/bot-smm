from __future__ import annotations

from fastapi import APIRouter

from src.config import settings
from src.webapp.deps import CurrentUser

router = APIRouter()


@router.get("/me")
async def me(user: CurrentUser) -> dict[str, object]:
    """Возвращает текущего пользователя Mini App.

    is_owner=True означает, что user.id совпадает с OWNER_ID. Используется
    фронтом, чтобы показывать/скрывать owner-only элементы (на момент Task 5
    отличий в UI нет, но контракт фиксируем заранее).
    """
    user_id = int(user.get("id", 0))
    return {
        "id": user_id,
        "username": user.get("username"),
        "first_name": user.get("first_name"),
        "is_owner": user_id == settings.owner_id,
    }
