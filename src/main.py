from __future__ import annotations

import asyncio
import signal
import sys
from contextlib import suppress

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from loguru import logger

from src.adminbot.bot import build_admin_bot, setup_admin_menu_buttons
from src.bot.handlers import router as bot_router
from src.bot.middleware import OwnerOnlyMiddleware
from src.bot.reactions import router as reactions_router
from src.config import settings
from src.scheduler import build_scheduler, set_scheduler
from src.storage.db import init_db
from src.webapp.server import build_webapp


def _setup_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)


async def _run_main_bot(shutdown_event: asyncio.Event) -> None:
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
        "main-bot started as @{} (owner_id={}, allowed_ids={})",
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

    allowed_updates = dp.resolve_used_update_types()
    logger.info("main-bot polling allowed_updates: {}", allowed_updates)

    async def _stop_on_signal() -> None:
        await shutdown_event.wait()
        logger.info("main-bot: stopping polling (shutdown requested)")
        await dp.stop_polling()

    polling_task = asyncio.create_task(
        dp.start_polling(bot, allowed_updates=allowed_updates),
        name="main-bot-polling",
    )
    stop_task = asyncio.create_task(_stop_on_signal(), name="main-bot-stop-watch")

    try:
        await polling_task
    except asyncio.CancelledError:
        polling_task.cancel()
        with suppress(BaseException):
            await polling_task
        raise
    finally:
        stop_task.cancel()
        with suppress(asyncio.CancelledError):
            await stop_task
        scheduler.shutdown(wait=False)
        await bot.session.close()


async def _run_admin_bot(shutdown_event: asyncio.Event) -> None:
    bot, dp = build_admin_bot()
    me = await bot.get_me()
    logger.info("admin-bot started as @{}", me.username)

    await setup_admin_menu_buttons(bot)

    async def _stop_on_signal() -> None:
        await shutdown_event.wait()
        logger.info("admin-bot: stopping polling (shutdown requested)")
        await dp.stop_polling()

    polling_task = asyncio.create_task(
        dp.start_polling(bot),
        name="admin-bot-polling",
    )
    stop_task = asyncio.create_task(_stop_on_signal(), name="admin-bot-stop-watch")

    try:
        await polling_task
    except asyncio.CancelledError:
        polling_task.cancel()
        with suppress(BaseException):
            await polling_task
        raise
    finally:
        stop_task.cancel()
        with suppress(asyncio.CancelledError):
            await stop_task
        await bot.session.close()


async def _run_webapp(shutdown_event: asyncio.Event) -> None:
    app = build_webapp()
    config = uvicorn.Config(
        app,
        host=settings.webapp_host,
        port=settings.webapp_port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )
    server = uvicorn.Server(config)

    async def _stop_on_signal() -> None:
        await shutdown_event.wait()
        logger.info("webapp: stopping uvicorn (shutdown requested)")
        server.should_exit = True

    logger.info(
        "webapp uvicorn binding {}:{}", settings.webapp_host, settings.webapp_port
    )

    serve_task = asyncio.create_task(server.serve(), name="webapp-serve")
    stop_task = asyncio.create_task(_stop_on_signal(), name="webapp-stop-watch")

    try:
        await serve_task
    except asyncio.CancelledError:
        server.should_exit = True
        with suppress(BaseException):
            await serve_task
        raise
    finally:
        stop_task.cancel()
        with suppress(asyncio.CancelledError):
            await stop_task


def _install_signal_handlers(shutdown_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def _on_signal() -> None:
        if not shutdown_event.is_set():
            logger.info("получен сигнал — инициирую graceful shutdown")
            shutdown_event.set()
        else:
            logger.warning("повторный сигнал во время shutdown — продолжаю ждать")

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            # Windows и некоторые embedded loops — фолбэк на дефолт OS-обработчики
            logger.warning("loop.add_signal_handler не поддерживается для {}", sig)


async def main() -> None:
    _setup_logging()
    await init_db()

    shutdown_event = asyncio.Event()
    _install_signal_handlers(shutdown_event)

    run_admin = bool(settings.admin_bot_token)
    if not run_admin:
        logger.warning(
            "ADMIN_BOT_TOKEN не задан — admin-бот и webapp пропускаются. "
            "Mini App будет недоступен."
        )

    service_names = ["main-bot"]
    if run_admin:
        service_names += ["admin-bot", "webapp"]
    logger.info("starting services: {}", service_names)

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_run_main_bot(shutdown_event), name="main-bot")
            if run_admin:
                tg.create_task(_run_admin_bot(shutdown_event), name="admin-bot")
                tg.create_task(_run_webapp(shutdown_event), name="webapp")
    except* Exception as eg:
        for exc in eg.exceptions:
            logger.exception("сервис упал: {}", exc)
        raise SystemExit(1) from eg


if __name__ == "__main__":
    asyncio.run(main())
