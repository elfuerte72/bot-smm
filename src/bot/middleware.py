from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from loguru import logger


class OwnerOnlyMiddleware(BaseMiddleware):
    """Пропускает только апдейты от пользователей из allowed_ids. Остальных молча игнорирует."""

    def __init__(self, allowed_ids: set[int]) -> None:
        self.allowed_ids = allowed_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id: int | None = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id is not None and user_id not in self.allowed_ids:
            logger.warning("Reject non-allowed update from user_id={}", user_id)
            if isinstance(event, CallbackQuery):
                await event.answer("Доступ запрещён", show_alert=False)
            return None

        return await handler(event, data)
