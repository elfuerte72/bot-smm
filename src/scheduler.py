from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from src.agent.news_agent import AgentError, generate_post
from src.agent.schemas import NoNews
from src.bot.handlers import send_preview_to_users
from src.config import settings
from src.storage import repo

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_CRON_JOB_PREFIX = "cron_generate_"
_SNAPSHOT_JOB_ID = "channel_snapshot"

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

    await send_preview_to_users(
        bot,
        result,
        chat_ids=chat_ids,
        actor_user_id=None,
        gen_mode="auto",
    )


async def channel_snapshot(bot: Bot) -> None:
    """Снимок числа подписчиков канала. Пишется в channel_snapshots.

    Источник — Bot API getChatMemberCount. Падение запроса логируем и
    пропускаем итерацию: пропуск в sparkline лучше, чем падение всей
    периодической задачи. Параллельно best-effort обновляем
    ``app_settings['channel_title']`` — нужен для /api/channel/stats.
    """
    channel_id = settings.channel_id
    try:
        member_count = await bot.get_chat_member_count(channel_id)
    except Exception:  # noqa: BLE001
        logger.exception("channel_snapshot: getChatMemberCount failed for {}", channel_id)
        return

    try:
        await repo.add_channel_snapshot(
            channel_id=str(channel_id),
            member_count=member_count,
        )
    except Exception:  # noqa: BLE001
        logger.exception("channel_snapshot: add_channel_snapshot failed")
        return

    try:
        chat = await bot.get_chat(channel_id)
        if chat.title:
            await repo.set_setting("channel_title", chat.title)
    except Exception:  # noqa: BLE001
        # title — best-effort, не должен валить snapshot
        logger.warning("channel_snapshot: get_chat для title не удался")

    logger.info("channel_snapshot: {} → {}", channel_id, member_count)


def _apply_times(scheduler: AsyncIOScheduler, bot: Bot, times: list[str]) -> list[str]:
    """Снимает все cron_generate-job'ы и заводит заново по списку HH:MM.

    Удаляются только job'ы с id-префиксом ``cron_generate_`` — channel_snapshot
    и любые другие фоновые задачи остаются на месте.
    Возвращает фактически применённые (с фильтрацией некорректных значений).
    """
    for job in list(scheduler.get_jobs()):
        if job.id.startswith(_CRON_JOB_PREFIX):
            scheduler.remove_job(job.id)
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
            id=f"{_CRON_JOB_PREFIX}{hour:02d}_{minute:02d}",
            replace_existing=True,
            misfire_grace_time=300,
        )
        applied.append(f"{hour:02d}:{minute:02d}")
        logger.info("Запланировано: cron_generate ежедневно в {:02d}:{:02d} {}", hour, minute, tz)
    return applied


def _schedule_channel_snapshot(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    """Регистрирует периодическую задачу снимков канала.

    Первый запуск — сразу (``next_run_time=datetime.now(tz)``), далее раз в
    ``CHANNEL_SNAPSHOT_INTERVAL_MINUTES``. Если интервал в конфиге <= 0,
    job не регистрируется (выключено).
    """
    interval_min = settings.channel_snapshot_interval_minutes
    if interval_min <= 0:
        logger.info("channel_snapshot: отключён (interval={} <= 0)", interval_min)
        return

    tz = _resolve_tz()
    scheduler.add_job(
        channel_snapshot,
        trigger=IntervalTrigger(minutes=interval_min, timezone=tz),
        kwargs={"bot": bot},
        id=_SNAPSHOT_JOB_ID,
        replace_existing=True,
        next_run_time=datetime.now(tz),
        misfire_grace_time=120,
    )
    logger.info("Запланировано: channel_snapshot раз в {} мин (tz={})", interval_min, tz)


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
    _schedule_channel_snapshot(scheduler, bot)
    return scheduler


async def reschedule_cron_times(times: list[str]) -> list[str]:
    """Пересобирает job'ы по новому списку HH:MM. Возвращает фактически применённые."""
    if _scheduler is None or _bot is None:
        raise RuntimeError("Scheduler не инициализирован (set_scheduler не вызван)")
    return _apply_times(_scheduler, _bot, times)
