from __future__ import annotations

import json
from dataclasses import dataclass

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
from src.bot.keyboards import edit_cancel_keyboard, main_menu_keyboard, preview_keyboard
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
        "Привет. Это SMM-бот для канала про AI и техкомпании.\n"
        "Жми кнопку ниже, чтобы сгенерировать новый пост.",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("generate"))
async def cmd_generate(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _run_generation(message)


@router.callback_query(F.data == "menu:generate")
async def cb_menu_generate(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cq.answer()
    if cq.message:
        await _run_generation(cq.message)


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
        await send_preview_to_users(bot, result, chat_ids=[cq.message.chat.id])


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


async def _run_generation(message: Message) -> None:
    """Ручной флоу генерации одному пользователю (тот, кто вызвал команду/кнопку)."""
    status = await message.answer("Ищу инфоповод и пишу пост…")
    try:
        exclude_urls = await repo.recent_source_urls()
        exclude_topics = await repo.recent_topics()
        result = await generate_post(
            exclude_urls=exclude_urls,
            exclude_topics=exclude_topics,
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
    if message.bot is not None:
        await send_preview_to_users(message.bot, result, chat_ids=[message.chat.id])


async def send_preview_to_users(
    bot: Bot,
    draft: PostDraft,
    *,
    chat_ids: list[int],
) -> None:
    """Сохраняет один draft и рассылает превью в каждый из chat_ids.

    Cron-сценарий шлёт обоим allowed-юзерам с одинаковым draft_id, чтобы
    race-защита на approve работала через статус в БД.
    """
    persisted = await _persist_draft(draft)
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


async def _persist_draft(draft: PostDraft) -> _PersistedDraft:
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
