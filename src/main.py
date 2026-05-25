from __future__ import annotations

import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from loguru import logger

from src.bot.handlers import router as bot_router
from src.bot.middleware import OwnerOnlyMiddleware
from src.bot.reactions import router as reactions_router
from src.config import settings
from src.scheduler import build_scheduler, set_scheduler
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

    owner_mw = OwnerOnlyMiddleware(settings.allowed_user_ids)
    dp.message.middleware(owner_mw)
    dp.callback_query.middleware(owner_mw)

    dp.include_router(bot_router)
    dp.include_router(reactions_router)

    me = await bot.get_me()
    logger.info(
        "Bot started as @{} (owner_id={}, allowed_ids={})",
        me.username,
        settings.owner_id,
        sorted(settings.allowed_user_ids),
    )

    await bot.set_my_commands(
        [
            BotCommand(command="generate", description="Сгенерировать пост"),
            BotCommand(command="status", description="Статус и расходы"),
            BotCommand(command="cron", description="Настроить расписание"),
            BotCommand(command="help", description="Помощь"),
        ]
    )

    scheduler = await build_scheduler(bot)
    set_scheduler(scheduler, bot)
    scheduler.start()

    # message_reaction_count по умолчанию НЕ присылается через getUpdates,
    # нужно явно перечислить allowed_updates. resolve_used_update_types
    # автоматически добавит его, увидев reactions_router.
    allowed_updates = dp.resolve_used_update_types()
    logger.info("polling allowed_updates: {}", allowed_updates)

    try:
        await dp.start_polling(bot, allowed_updates=allowed_updates)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
