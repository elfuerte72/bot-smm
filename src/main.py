from __future__ import annotations

import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger

from src.bot.handlers import router as bot_router
from src.bot.middleware import OwnerOnlyMiddleware
from src.config import settings
from src.storage.db import init_db


def _setup_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)


async def main() -> None:
    _setup_logging()

    await init_db()

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    owner_mw = OwnerOnlyMiddleware(settings.owner_id)
    dp.message.middleware(owner_mw)
    dp.callback_query.middleware(owner_mw)

    dp.include_router(bot_router)

    me = await bot.get_me()
    logger.info("Bot started as @{} (owner_id={})", me.username, settings.owner_id)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
