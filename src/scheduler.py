from __future__ import annotations

import re
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

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

_scheduler: AsyncIOScheduler | None = None
_bot: Bot | None = None


def set_scheduler(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    global _scheduler, _bot
    _scheduler = scheduler
    _bot = bot


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


def parse_hhmm(s: str) -> tuple[int, int] | None:
    m = _HHMM_RE.match(s.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _resolve_tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.cron_tz)
    except ZoneInfoNotFoundError:
        logger.warning(
            "cron_tz='{}' не найдена в системе, использую Europe/Moscow",
            settings.cron_tz,
        )
        return ZoneInfo("Europe/Moscow")


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


def _apply_times(scheduler: AsyncIOScheduler, bot: Bot, times: list[str]) -> list[str]:
    """Снимает все cron-job'ы и заводит заново по списку HH:MM. Возвращает
    фактически применённые (с фильтрацией некорректных значений)."""
    scheduler.remove_all_jobs()
    tz = _resolve_tz()
    applied: list[str] = []
    for hhmm in times:
        parsed = parse_hhmm(hhmm)
        if parsed is None:
            logger.warning("cron_times: пропускаю некорректное значение '{}'", hhmm)
            continue
        hour, minute = parsed
        scheduler.add_job(
            cron_generate,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=tz),
            kwargs={"bot": bot},
            id=f"cron_generate_{hour:02d}_{minute:02d}",
            replace_existing=True,
            misfire_grace_time=300,
        )
        applied.append(f"{hour:02d}:{minute:02d}")
        logger.info("Запланировано: cron_generate ежедневно в {:02d}:{:02d} {}", hour, minute, tz)
    return applied


async def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Создаёт планировщик. Источник правды для cron_times — БД.

    Если в БД пусто (первый запуск), берём дефолты из settings.cron_times и
    сохраняем их в БД, чтобы дальше .env не был обязателен.
    """
    tz = _resolve_tz()
    scheduler = AsyncIOScheduler(timezone=tz)

    times = await repo.get_cron_times()
    if times is None:
        times = list(settings.cron_times)
        await repo.set_cron_times(times)
        logger.info("Seeded cron_times из .env в БД: {}", times)

    _apply_times(scheduler, bot, times)
    return scheduler


async def reschedule_cron_times(times: list[str]) -> list[str]:
    """Пересобирает job'ы по новому списку HH:MM. Возвращает фактически применённые."""
    if _scheduler is None or _bot is None:
        raise RuntimeError("Scheduler не инициализирован (set_scheduler не вызван)")
    return _apply_times(_scheduler, _bot, times)
