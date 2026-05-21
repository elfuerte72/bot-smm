from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from src.agent.news_agent import AgentError, generate_post
from src.agent.schemas import NoNews
from src.bot.handlers import send_preview_to_users
from src.config import settings
from src.storage import repo


async def cron_generate(bot: Bot) -> None:
    """Задача по расписанию: генерирует пост и шлёт превью всем allowed-юзерам.

    Защита от дубля публикации — на стороне БД (claim_for_publish). Здесь
    просто шлём один и тот же draft_id обоим: кто первый одобрит, тот и
    публикует.
    """
    chat_ids = sorted(settings.allowed_user_ids)
    if not chat_ids:
        logger.warning("cron_generate: пустой allowed_user_ids, пропускаю")
        return

    logger.info("cron_generate: старт, получатели={}", chat_ids)

    try:
        exclude_urls = await repo.recent_source_urls()
        exclude_topics = await repo.recent_topics()
        result = await generate_post(
            exclude_urls=exclude_urls,
            exclude_topics=exclude_topics,
        )
    except AgentError as e:
        logger.warning("cron_generate: AgentError {}", e)
        return
    except Exception:  # noqa: BLE001
        logger.exception("cron_generate: непредвиденная ошибка генератора")
        return

    if isinstance(result, NoNews):
        logger.info(
            "cron_generate: NoNews ({})",
            result.reason or "без причины",
        )
        return

    await send_preview_to_users(bot, result, chat_ids=chat_ids)


def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Создаёт планировщик с задачами cron_generate на заданные часы.

    Время и таймзона берутся из settings.cron_times / settings.cron_tz.
    Если хотя бы одно значение времени некорректно — пишем warning и
    пропускаем его, остальные продолжают работать.
    """
    try:
        tz = ZoneInfo(settings.cron_tz)
    except ZoneInfoNotFoundError:
        logger.warning(
            "cron_tz='{}' не найдена в системе, использую Europe/Moscow",
            settings.cron_tz,
        )
        tz = ZoneInfo("Europe/Moscow")

    scheduler = AsyncIOScheduler(timezone=tz)

    for hhmm in settings.cron_times:
        try:
            hour_s, minute_s = hhmm.split(":", 1)
            hour, minute = int(hour_s), int(minute_s)
        except ValueError:
            logger.warning("cron_times: пропускаю некорректное значение '{}'", hhmm)
            continue
        scheduler.add_job(
            cron_generate,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=tz),
            kwargs={"bot": bot},
            id=f"cron_generate_{hour:02d}_{minute:02d}",
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info("Запланировано: cron_generate ежедневно в {:02d}:{:02d} {}", hour, minute, tz)

    return scheduler
