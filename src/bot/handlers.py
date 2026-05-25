from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC
from difflib import unified_diff
from urllib.parse import urlparse

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)
from loguru import logger

from src.agent.news_agent import AgentError, generate_post
from src.agent.schemas import NoNews, PostDraft
from src.bot.keyboards import (
    edit_cancel_keyboard,
    generation_mode_keyboard,
    main_menu_keyboard,
    manual_config_keyboard,
    preview_keyboard,
)
from src.config import settings
from src.media.og_image import fetch_best_image, normalize_for_telegram
from src.storage import repo
from src.utils.tg_format import (
    fits_caption,
    format_post,
    truncate_to_message,
)

router = Router()


class EditState(StatesGroup):
    waiting_for_text = State()


class CronState(StatesGroup):
    waiting_for_times = State()


class ManualGenState(StatesGroup):
    waiting_for_topic = State()
    waiting_for_url = State()


@dataclass(slots=True)
class _PersistedDraft:
    draft_id: int
    formatted_text: str
    image_bytes: bytes | None
    primary_source_url: str


# ──────────────────────────────────────────────────────────────────────────────
# /start, /generate, меню
# ──────────────────────────────────────────────────────────────────────────────


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Добро пожаловать, начальник. Это главное меню новостного отдела Aibromotion.",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("generate"))
async def cmd_generate(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Как генерим пост?",
        reply_markup=generation_mode_keyboard(),
    )


@router.callback_query(F.data == "menu:generate")
async def cb_menu_generate(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cq.answer()
    if cq.message:
        await cq.message.answer(
            "Как генерим пост?",
            reply_markup=generation_mode_keyboard(),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Меню выбора режима генерации
# ──────────────────────────────────────────────────────────────────────────────


@router.callback_query(F.data == "gen:auto")
async def cb_gen_auto(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cq.answer()
    await _strip_keyboard(cq)
    if cq.message:
        await _run_generation(cq.message)


@router.callback_query(F.data == "gen:manual")
async def cb_gen_manual(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cq.answer()
    if cq.message is None:
        return
    try:
        await cq.message.edit_text(
            "Ручная настройка. Выбери источник:",
            reply_markup=manual_config_keyboard(),
        )
    except TelegramBadRequest:
        await cq.message.answer(
            "Ручная настройка. Выбери источник:",
            reply_markup=manual_config_keyboard(),
        )


@router.callback_query(F.data == "gen:back")
async def cb_gen_back(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cq.answer()
    if cq.message is None:
        return
    try:
        await cq.message.edit_text(
            "Как генерим пост?",
            reply_markup=generation_mode_keyboard(),
        )
    except TelegramBadRequest:
        await cq.message.answer(
            "Как генерим пост?",
            reply_markup=generation_mode_keyboard(),
        )


@router.callback_query(F.data == "gen:topic")
async def cb_gen_topic(cq: CallbackQuery, state: FSMContext) -> None:
    await cq.answer()
    if cq.message is None:
        return
    await state.set_state(ManualGenState.waiting_for_topic)
    await _strip_keyboard(cq)
    await cq.message.answer(
        "Пришли тему или короткое описание события одним сообщением.\n"
        "Например: «Tesla отчёт за Q1 2026» или «xAI открыл API для Grok 4: "
        "цены, лимиты, доступ».\n\n"
        "/cancel — отмена."
    )


@router.callback_query(F.data == "gen:url")
async def cb_gen_url(cq: CallbackQuery, state: FSMContext) -> None:
    await cq.answer()
    if cq.message is None:
        return
    await state.set_state(ManualGenState.waiting_for_url)
    await _strip_keyboard(cq)
    await cq.message.answer(
        "Пришли ссылку на статью (http/https). Бот прочитает её и напишет пост "
        "в стиле канала.\n\n"
        "/cancel — отмена."
    )


@router.message(ManualGenState.waiting_for_topic, F.text)
async def on_manual_topic(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if len(raw) < 3:
        await message.answer("Слишком коротко. Опиши тему подробнее или /cancel.")
        return
    if len(raw) > 500:
        await message.answer("Слишком длинно (>500 символов). Сократи или /cancel.")
        return
    await state.clear()
    await _run_generation(message, topic=raw)


@router.message(ManualGenState.waiting_for_url, F.text)
async def on_manual_url(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        await message.answer(
            "Это не похоже на ссылку. Жду URL вида https://example.com/article "
            "или /cancel."
        )
        return
    await state.clear()
    await _run_generation(message, source_url=raw)


# ──────────────────────────────────────────────────────────────────────────────
# /help, /status, /cron, /cancel
# ──────────────────────────────────────────────────────────────────────────────

HELP_TEXT = (
    "<b>Команды бота</b>\n\n"
    "• /start — открыть главное меню\n"
    "• /generate — выбрать режим генерации поста\n"
    "• /status — канал публикации, расписание автогенерации, расходы API\n"
    "• /cron — изменить расписание автогенерации (HH:MM через запятую)\n"
    "• /cancel — отменить текущее действие (правку, ввод темы/URL, расписание)\n"
    "• /help — эта справка\n\n"
    "<b>Режимы генерации</b>\n"
    "После «🚀 Сгенерировать пост» бот спрашивает, как генерим:\n"
    "• <b>⚡ Авто</b> — свежий AI-инфоповод (как в автогенерации).\n"
    "• <b>⚙️ Ручная настройка</b> → <b>✏️ Своя тема</b> (ты пишешь тему/бриф) "
    "или <b>🔗 По ссылке</b> (ты даёшь URL статьи, бот пишет пост по ней).\n\n"
    "<b>Как работать с постом</b>\n"
    "Бот пришлёт превью с кнопками:\n"
    "«Опубликовать» — отправить в канал.\n"
    "«Перегенерировать» — попросить другую новость.\n"
    "«Редактировать» — заменить тело поста своим текстом.\n"
    "«Отклонить» — закрыть черновик без публикации.\n\n"
    "Автогенерация дважды в день шлёт превью обоим админам — кто первый "
    "одобрил, тот и опубликовал."
)


@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(HELP_TEXT)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    await state.clear()
    if current:
        await message.answer("Отменено.", reply_markup=main_menu_keyboard())
    else:
        await message.answer("Нечего отменять.", reply_markup=main_menu_keyboard())


@router.message(Command("status"))
async def cmd_status(message: Message, state: FSMContext) -> None:
    await state.clear()
    if message.bot is None:
        return
    await message.answer(await _build_status_text(message.bot))


@router.message(Command("cron"))
async def cmd_cron(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _enter_cron_flow(message, state)


@router.callback_query(F.data == "menu:status")
async def cb_menu_status(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cq.answer()
    if cq.message and cq.bot:
        await cq.message.answer(await _build_status_text(cq.bot))


@router.callback_query(F.data == "menu:cron")
async def cb_menu_cron(cq: CallbackQuery, state: FSMContext) -> None:
    await cq.answer()
    if cq.message:
        await _enter_cron_flow(cq.message, state)


@router.callback_query(F.data == "menu:help")
async def cb_menu_help(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cq.answer()
    if cq.message:
        await cq.message.answer(HELP_TEXT)


async def _build_status_text(bot: Bot) -> str:
    """Собирает текст для /status: канал, расписание, расходы."""
    # 1) Канал
    channel_repr = _escape_html(str(settings.channel_id))
    channel_title: str | None = None
    try:
        chat = await bot.get_chat(settings.channel_id)
        if chat.title:
            channel_title = chat.title
    except Exception as e:  # noqa: BLE001
        logger.warning("status: не удалось получить чат канала: {}", e)

    channel_line = f"<b>Канал:</b> {channel_repr}"
    if channel_title:
        channel_line = f"<b>Канал:</b> {_escape_html(channel_title)} ({channel_repr})"

    # 2) Расписание
    from src.scheduler import get_scheduler

    schedule_lines: list[str] = []
    scheduler = get_scheduler()
    if scheduler is None:
        schedule_lines.append("Планировщик не запущен.")
    else:
        jobs = sorted(
            scheduler.get_jobs(),
            key=lambda j: (j.next_run_time or _far_future()),
        )
        if not jobs:
            schedule_lines.append("Расписание пустое.")
        else:
            for j in jobs:
                t = j.next_run_time
                next_s = t.strftime("%Y-%m-%d %H:%M") if t else "—"
                hhmm = j.id.replace("cron_generate_", "").replace("_", ":")
                schedule_lines.append(f"• {hhmm} (next: {next_s})")
    schedule_block = "<b>Расписание ({}):</b>\n{}".format(
        _escape_html(settings.cron_tz),
        "\n".join(schedule_lines),
    )

    # 3) Расходы API — локальный счётчик
    summary = await repo.usage_summary()
    by_day = await repo.usage_by_day(days=7)

    cost_lines = [
        "<b>Расходы Claude API (по логам бота):</b>",
        "• Сегодня: ${:.4f} ({} выз.)".format(
            float(summary["today"]["usd"]), int(summary["today"]["calls"])
        ),
        "• За неделю: ${:.4f} ({} выз.)".format(
            float(summary["week"]["usd"]), int(summary["week"]["calls"])
        ),
        "• Этот месяц: ${:.4f} ({} выз.)".format(
            float(summary["month"]["usd"]), int(summary["month"]["calls"])
        ),
        "• Всего: ${:.4f} ({} выз.)".format(
            float(summary["total"]["usd"]), int(summary["total"]["calls"])
        ),
    ]
    if by_day:
        cost_lines.append("")
        cost_lines.append("<b>Последние 7 дней (UTC):</b>")
        for r in by_day:
            cost_lines.append(
                "  {}: ${:.4f} ({} выз.)".format(r["date"], float(r["usd"]), int(r["calls"]))
            )
    cost_block = "\n".join(cost_lines)

    return "\n\n".join([channel_line, schedule_block, cost_block])


async def _enter_cron_flow(target: Message, state: FSMContext) -> None:
    """Общая точка для /cron и кнопки «⏰ Расписание»: показывает текущее
    расписание и переводит в FSM-state ожидания нового списка."""
    await state.clear()
    current = await repo.get_cron_times() or list(settings.cron_times)
    current_str = ", ".join(current) if current else "(пусто)"
    await state.set_state(CronState.waiting_for_times)
    await target.answer(
        f"Текущее расписание: <b>{_escape_html(current_str)}</b> "
        f"({_escape_html(settings.cron_tz)}).\n\n"
        "Пришли новый список времён через запятую в формате HH:MM.\n"
        "Пример: <code>09:00,14:30,20:00</code>\n\n"
        "/cancel — отмена."
    )


@router.message(CronState.waiting_for_times, F.text)
async def on_cron_times(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Пустой ввод. Пример: 09:00,14:30 или /cancel.")
        return

    from src.scheduler import parse_hhmm, reschedule_cron_times

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    parsed: list[str] = []
    for p in parts:
        hm = parse_hhmm(p)
        if hm is None:
            await message.answer(
                f"Не понял «{_escape_html(p)}». Формат HH:MM, например 09:00. "
                "Попробуй ещё раз или /cancel."
            )
            return
        parsed.append(f"{hm[0]:02d}:{hm[1]:02d}")

    # дедуп + сортировка
    unique = sorted(set(parsed))
    if not unique:
        await message.answer("Не вижу ни одного валидного времени. Попробуй ещё раз.")
        return

    await repo.set_cron_times(unique)
    try:
        applied = await reschedule_cron_times(unique)
    except RuntimeError as e:
        await state.clear()
        await message.answer(f"Не удалось применить: {e}")
        return

    await state.clear()
    await message.answer(
        "Готово. Новое расписание: <b>{}</b> ({}).".format(
            _escape_html(", ".join(applied)),
            _escape_html(settings.cron_tz),
        )
    )


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _far_future():
    from datetime import datetime

    return datetime.max.replace(tzinfo=UTC)


# ──────────────────────────────────────────────────────────────────────────────
# Callbacks превью
# ──────────────────────────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("approve:"))
async def cb_approve(cq: CallbackQuery) -> None:
    draft_id = _parse_id(cq.data)
    if draft_id is None or cq.message is None:
        await cq.answer("Не удалось разобрать draft id", show_alert=True)
        return

    draft = await repo.get_draft(draft_id)
    if not draft:
        await cq.answer("Черновик не найден", show_alert=True)
        return

    if not await repo.claim_for_publish(draft_id):
        # кто-то другой уже опубликовал/отклонил этот черновик
        await cq.answer("Уже обработано")
        await _strip_keyboard(cq)
        return

    bot = cq.bot
    if bot is None:
        await repo.release_publish(draft_id)
        return

    text = draft.formatted_text
    file_id = draft.image_file_id

    try:
        sent = await _publish_to_channel(bot, text=text, file_id=file_id, draft=draft)
    except Exception as e:  # noqa: BLE001
        logger.exception("Publish failed")
        await repo.release_publish(draft_id)
        await cq.answer(f"Ошибка публикации: {e}", show_alert=True)
        return

    title = _title_from_draft(draft.raw_json)
    await repo.mark_published(
        draft_id,
        source_url=draft.primary_source_url,
        title=title,
        tg_message_id=sent.message_id,
    )
    actor_id = cq.from_user.id if cq.from_user else None
    await repo.record_draft_event(
        draft_id,
        "approved",
        actor_user_id=actor_id,
        payload={"tg_message_id": sent.message_id, "channel_id": str(settings.channel_id)},
    )
    await _strip_keyboard(cq)
    await cq.answer("Опубликовано")
    await cq.message.answer(f"Пост #{sent.message_id} опубликован в канале.")


@router.callback_query(F.data.startswith("regen:"))
async def cb_regenerate(cq: CallbackQuery) -> None:
    draft_id = _parse_id(cq.data)
    if draft_id is None or cq.message is None:
        await cq.answer("Не удалось разобрать draft id", show_alert=True)
        return

    draft = await repo.get_draft(draft_id)
    if not draft:
        await cq.answer("Черновик не найден", show_alert=True)
        return

    # помечаем текущий черновик rejected ДО генерации, чтобы его заголовок
    # тоже попал в exclude_topics. Атомарный переход защищает от двойного
    # запуска перегенерации с разных устройств.
    if not await repo.mark_rejected(draft_id):
        await cq.answer("Уже обработано")
        await _strip_keyboard(cq)
        return

    actor_id = cq.from_user.id if cq.from_user else None
    await repo.record_draft_event(
        draft_id,
        "rejected",
        actor_user_id=actor_id,
        payload={"reason": "regenerate_replaced"},
    )

    await cq.answer("Генерирую заново…")
    await _strip_keyboard(cq)

    status = await cq.message.answer("Ищу другой инфоповод…")

    try:
        exclude_urls = await repo.recent_source_urls()
        if draft.primary_source_url not in exclude_urls:
            exclude_urls.append(draft.primary_source_url)
        exclude_topics = await repo.recent_topics()
        result = await generate_post(
            exclude_urls=exclude_urls,
            exclude_topics=exclude_topics,
        )
    except AgentError as e:
        await status.edit_text(f"Не получилось перегенерировать: {e}")
        return
    except Exception as e:  # noqa: BLE001
        logger.exception("Unexpected agent error during regenerate")
        await status.edit_text(f"Внутренняя ошибка: {e}")
        return

    if isinstance(result, NoNews):
        msg = "Других подходящих инфоповодов сейчас нет."
        if result.reason:
            msg += f"\nПричина: {result.reason}"
        await status.edit_text(msg)
        return

    await status.delete()
    bot = cq.bot
    if bot is not None:
        new_draft_id = await send_preview_to_users(
            bot,
            result,
            chat_ids=[cq.message.chat.id],
            actor_user_id=actor_id,
            gen_mode="auto",
        )
        await repo.record_draft_event(
            draft_id,
            "regenerated_from",
            actor_user_id=actor_id,
            payload={"new_draft_id": new_draft_id, "new_title": result.title},
        )


@router.callback_query(F.data.startswith("edit:"))
async def cb_edit(cq: CallbackQuery, state: FSMContext) -> None:
    draft_id = _parse_id(cq.data)
    if draft_id is None or cq.message is None:
        await cq.answer("Не удалось разобрать draft id", show_alert=True)
        return

    await state.set_state(EditState.waiting_for_text)
    await state.update_data(draft_id=draft_id)

    await cq.answer()
    await cq.message.answer(
        "Пришли новый текст поста одним сообщением. "
        "Он заменит тело текущего черновика, картинка и ссылка останутся.",
        reply_markup=edit_cancel_keyboard(draft_id),
    )


@router.callback_query(F.data.startswith("editcancel:"))
async def cb_edit_cancel(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cq.answer("Правка отменена")
    if cq.message:
        await cq.message.delete()


@router.callback_query(F.data.startswith("reject:"))
async def cb_reject(cq: CallbackQuery) -> None:
    draft_id = _parse_id(cq.data)
    if draft_id is None:
        await cq.answer("Не удалось разобрать draft id", show_alert=True)
        return

    if not await repo.mark_rejected(draft_id):
        await cq.answer("Уже обработано")
        await _strip_keyboard(cq)
        return
    actor_id = cq.from_user.id if cq.from_user else None
    await repo.record_draft_event(
        draft_id,
        "rejected",
        actor_user_id=actor_id,
        payload={"reason": "manual_reject"},
    )
    await _strip_keyboard(cq)
    await cq.answer("Отклонено")


@router.message(EditState.waiting_for_text, F.text)
async def on_edit_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    draft_id: int | None = data.get("draft_id")
    await state.clear()

    if draft_id is None or not message.text:
        await message.answer("Не нашёл, к какому черновику относится правка.")
        return

    draft = await repo.get_draft(draft_id)
    if not draft:
        await message.answer("Черновик не найден.")
        return

    new_text = message.text.strip()
    old_text = draft.formatted_text
    diff_unified = "\n".join(
        unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile="old",
            tofile="new",
            lineterm="",
        )
    )
    actor_id = message.from_user.id if message.from_user else None
    await repo.record_draft_event(
        draft_id,
        "edited",
        actor_user_id=actor_id,
        payload={"old_text": old_text, "new_text": new_text, "diff_unified": diff_unified},
    )
    await repo.update_draft_text(draft_id, new_text)

    refreshed = await repo.get_draft(draft_id)
    if not refreshed or message.bot is None:
        return

    await _do_send_preview(
        bot=message.bot,
        chat_id=message.chat.id,
        draft_id=draft_id,
        text=refreshed.formatted_text,
        image_bytes=None,
        image_file_id=refreshed.image_file_id,
        primary_source_url=refreshed.primary_source_url,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Catch-all: любое прочее сообщение → меню (только когда нет активного FSM-state)
# ──────────────────────────────────────────────────────────────────────────────


@router.message(StateFilter(None))
async def fallback_menu(message: Message) -> None:
    await message.answer(
        "Используй кнопку ниже, чтобы сгенерировать новый пост.",
        reply_markup=main_menu_keyboard(),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Публичные хелперы — переиспользуются командой /generate, кнопкой меню и cron
# ──────────────────────────────────────────────────────────────────────────────


async def _run_generation(
    message: Message,
    *,
    topic: str | None = None,
    source_url: str | None = None,
) -> None:
    """Ручной флоу генерации одному пользователю (тот, кто вызвал команду/кнопку).

    `topic` — пользовательская тема, перебивает AI-тематику системного промпта.
    `source_url` — прямой URL источника: бот пишет пост по содержимому статьи.
    Для URL-режима фильтры по уже опубликованным URL/темам отключаем,
    пользователь явно выбрал источник.
    """
    if source_url:
        status_text = "Читаю статью и пишу пост…"
        gen_mode = "url"
    elif topic:
        status_text = "Ищу инфоповод по теме и пишу пост…"
        gen_mode = "topic"
    else:
        status_text = "Ищу инфоповод и пишу пост…"
        gen_mode = "auto"
    status = await message.answer(status_text)
    try:
        if source_url:
            exclude_urls: list[str] = []
            exclude_topics: list[str] = []
        else:
            exclude_urls = await repo.recent_source_urls()
            exclude_topics = await repo.recent_topics()
        result = await generate_post(
            exclude_urls=exclude_urls,
            exclude_topics=exclude_topics,
            topic=topic,
            source_url=source_url,
        )
    except AgentError as e:
        await status.edit_text(f"Не получилось сгенерировать пост: {e}")
        return
    except Exception as e:  # noqa: BLE001
        logger.exception("Unexpected agent error")
        await status.edit_text(f"Внутренняя ошибка: {e}")
        return

    if isinstance(result, NoNews):
        msg = "Сейчас нет подходящего инфоповода."
        if result.reason:
            msg += f"\nПричина: {result.reason}"
        await status.edit_text(msg)
        return

    await status.delete()
    actor_user_id = message.from_user.id if message.from_user else None
    if message.bot is not None:
        await send_preview_to_users(
            message.bot,
            result,
            chat_ids=[message.chat.id],
            actor_user_id=actor_user_id,
            gen_mode=gen_mode,
            gen_topic=topic,
        )


async def send_preview_to_users(
    bot: Bot,
    draft: PostDraft,
    *,
    chat_ids: list[int],
    actor_user_id: int | None,
    gen_mode: str,
    gen_topic: str | None = None,
) -> int:
    """Сохраняет один draft и рассылает превью в каждый из chat_ids.

    Cron-сценарий шлёт обоим allowed-юзерам с одинаковым draft_id, чтобы
    race-защита на approve работала через статус в БД. Возвращает draft_id,
    чтобы вызвавший мог записать связанный audit-event (например
    regenerated_from на старый драфт после успешной регенерации).
    """
    persisted = await _persist_draft(
        draft,
        actor_user_id=actor_user_id,
        gen_mode=gen_mode,
        gen_topic=gen_topic,
    )
    image_file_id: str | None = None
    image_bytes_remaining = persisted.image_bytes

    for chat_id in chat_ids:
        try:
            new_file_id = await _do_send_preview(
                bot=bot,
                chat_id=chat_id,
                draft_id=persisted.draft_id,
                text=persisted.formatted_text,
                image_bytes=image_bytes_remaining,
                image_file_id=image_file_id,
                primary_source_url=persisted.primary_source_url,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось отправить превью chat_id={}", chat_id)
            continue

        if new_file_id and image_file_id is None:
            image_file_id = new_file_id
            image_bytes_remaining = None
            await repo.set_image_file_id(persisted.draft_id, new_file_id)

    return persisted.draft_id


async def _persist_draft(
    draft: PostDraft,
    *,
    actor_user_id: int | None,
    gen_mode: str,
    gen_topic: str | None,
) -> _PersistedDraft:
    formatted = format_post(draft)
    source_urls = [str(draft.primary_source_url)] + [str(u) for u in draft.extra_sources]
    fetched = await fetch_best_image(source_urls)
    image_url = fetched.url if fetched else None

    draft_id = await repo.save_draft(
        raw_json=json.dumps(draft.model_dump(mode="json"), ensure_ascii=False),
        formatted_text=formatted,
        image_url=image_url,
        primary_source_url=str(draft.primary_source_url),
    )

    created_payload: dict[str, object] = {
        "mode": gen_mode,
        "source_url": str(draft.primary_source_url),
        "title": draft.title,
    }
    if gen_topic:
        created_payload["topic"] = gen_topic
    await repo.record_draft_event(
        draft_id,
        "created",
        actor_user_id=actor_user_id,
        payload=created_payload,
    )

    return _PersistedDraft(
        draft_id=draft_id,
        formatted_text=formatted,
        image_bytes=fetched.content if fetched else None,
        primary_source_url=str(draft.primary_source_url),
    )


# ──────────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────────


def _parse_id(data: str | None) -> int | None:
    if not data or ":" not in data:
        return None
    try:
        return int(data.split(":", 1)[1])
    except ValueError:
        return None


def _title_from_draft(raw_json: str) -> str:
    try:
        return json.loads(raw_json).get("title", "(без заголовка)")
    except json.JSONDecodeError:
        return "(без заголовка)"


async def _strip_keyboard(cq: CallbackQuery) -> None:
    if cq.message is None:
        return
    try:
        await cq.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass


async def _publish_to_channel(
    bot: Bot,
    *,
    text: str,
    file_id: str | None,
    draft: repo.DraftRow,
) -> Message:
    """Публикация поста в канал. При IMAGE_PROCESS_FAILED на file_id — фолбэк
    на текст + link-preview по primary_source_url (без картинки)."""
    if file_id and fits_caption(text):
        try:
            return await bot.send_photo(
                chat_id=settings.channel_id, photo=file_id, caption=text
            )
        except TelegramBadRequest as e:
            logger.warning("Канал: send_photo упал ({}), фолбэк на link-preview", e)

    if file_id:
        # Здесь либо caption переполнен, либо send_photo упал и мы попали сюда
        # снова через else. В обоих случаях пытаемся отправить фото отдельно,
        # а текст — отдельным сообщением. Если и тут не получилось — только текст.
        if not fits_caption(text):
            logger.warning("Каналу: caption > 1024 ({}), шлём двумя сообщениями", len(text))
        try:
            await bot.send_photo(chat_id=settings.channel_id, photo=file_id)
        except TelegramBadRequest as e:
            logger.warning("Канал: split-photo упал ({}), шлём только текст", e)
        return await bot.send_message(
            chat_id=settings.channel_id,
            text=truncate_to_message(text),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    return await bot.send_message(
        chat_id=settings.channel_id,
        text=truncate_to_message(text),
        link_preview_options=LinkPreviewOptions(
            url=draft.primary_source_url,
            prefer_large_media=True,
            show_above_text=True,
        ),
    )


async def _send_photo_with_retry(
    bot: Bot,
    *,
    chat_id: int,
    photo: str | BufferedInputFile,
    image_bytes: bytes | None,
    fresh_upload: bool,
    caption: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """send_photo с одним retry через перекодирование Pillow → JPEG.

    Telegram часто возвращает IMAGE_PROCESS_FAILED на картинки CDN с фейковым
    .jpg расширением (на деле WebP/прогрессивный JPEG). После нормализации
    в чистый baseline JPEG картинка проходит. Если retry тоже не помог
    или у нас только file_id (image_bytes is None) — возвращаем None, чтобы
    вызвавший код упал на текстовый фолбэк.
    """
    try:
        return await bot.send_photo(
            chat_id=chat_id, photo=photo, caption=caption, reply_markup=reply_markup
        )
    except TelegramBadRequest as e:
        if not (fresh_upload and image_bytes and "IMAGE_PROCESS" in str(e)):
            logger.warning("send_photo не удался ({}); фолбэк без retry", e)
            return None

    normalized = normalize_for_telegram(image_bytes)
    if not normalized:
        logger.warning("normalize_for_telegram вернул None, фолбэк на текст")
        return None

    try:
        m = await bot.send_photo(
            chat_id=chat_id,
            photo=BufferedInputFile(normalized, filename="cover.jpg"),
            caption=caption,
            reply_markup=reply_markup,
        )
        logger.info("send_photo прошёл после нормализации Pillow")
        return m
    except TelegramBadRequest as e2:
        logger.warning("send_photo упал даже после нормализации: {}", e2)
        return None


async def _do_send_preview(
    *,
    bot: Bot,
    chat_id: int,
    draft_id: int,
    text: str,
    image_bytes: bytes | None,
    image_file_id: str | None,
    primary_source_url: str,
) -> str | None:
    """Шлёт превью в указанный чат. Возвращает file_id, если впервые загружали байты.

    Главный путь: одно сообщение photo+caption (если есть картинка и текст
    влезает в caption-лимит). Если картинки нет — текст + link-preview.
    Если caption переполнен — фото и текст отдельными сообщениями.
    Если Telegram отбил картинку (IMAGE_PROCESS_FAILED и пр.) —
    мы либо перекодируем, либо падаем в текстовый фолбэк с link-preview.
    """
    kb: InlineKeyboardMarkup = preview_keyboard(draft_id)

    photo: str | BufferedInputFile | None
    fresh_upload = False
    if image_file_id:
        photo = image_file_id
    elif image_bytes:
        photo = BufferedInputFile(image_bytes, filename="cover.jpg")
        fresh_upload = True
    else:
        photo = None

    if photo is not None and fits_caption(text):
        m = await _send_photo_with_retry(
            bot,
            chat_id=chat_id,
            photo=photo,
            image_bytes=image_bytes,
            fresh_upload=fresh_upload,
            caption=text,
            reply_markup=kb,
        )
        if m is not None:
            return m.photo[-1].file_id if fresh_upload and m.photo else None
        # фото не зашло — падаем в текстовый фолбэк ниже

    elif photo is not None:
        logger.warning("Caption > 1024 ({}), splitting preview", len(text))
        m = await _send_photo_with_retry(
            bot,
            chat_id=chat_id,
            photo=photo,
            image_bytes=image_bytes,
            fresh_upload=fresh_upload,
        )
        new_file_id = m.photo[-1].file_id if (m and fresh_upload and m.photo) else None
        await bot.send_message(
            chat_id=chat_id,
            text=truncate_to_message(text),
            reply_markup=kb,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return new_file_id

    await bot.send_message(
        chat_id=chat_id,
        text=truncate_to_message(text),
        reply_markup=kb,
        link_preview_options=LinkPreviewOptions(
            url=primary_source_url,
            prefer_large_media=True,
            show_above_text=True,
        ),
    )
    return None
