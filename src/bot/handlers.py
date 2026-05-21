from __future__ import annotations

import json
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
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
from src.bot.keyboards import edit_cancel_keyboard, preview_keyboard
from src.config import settings
from src.media.og_image import fetch_best_image
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
class _SentPreview:
    photo_message_id: int | None
    text_message_id: int


# ──────────────────────────────────────────────────────────────────────────────
# /start, /generate
# ──────────────────────────────────────────────────────────────────────────────


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет. Это SMM-бот для канала про AI и техкомпании.\n\n"
        "Команды:\n"
        "• /generate — сгенерировать пост по свежему инфоповоду.\n"
        "После генерации я пришлю превью с кнопками публикации, перегенерации и правки."
    )


@router.message(Command("generate"))
async def cmd_generate(message: Message, state: FSMContext) -> None:
    await state.clear()

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
    await _send_preview(message, result)


# ──────────────────────────────────────────────────────────────────────────────
# Callbacks
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
    if draft.status != "draft":
        await cq.answer(f"Уже {draft.status}", show_alert=True)
        return

    bot = cq.bot
    if bot is None:
        return

    text = draft.formatted_text
    file_id = draft.image_file_id

    try:
        if file_id and fits_caption(text):
            sent = await bot.send_photo(
                chat_id=settings.channel_id,
                photo=file_id,
                caption=text,
            )
        elif file_id:
            # caption переполнен (редкий случай — модель нарушила лимит).
            # Шлём фото с уведомлением и отдельным сообщением текст.
            logger.warning("Caption > 1024 chars ({}), splitting", len(text))
            await bot.send_photo(chat_id=settings.channel_id, photo=file_id)
            sent = await bot.send_message(
                chat_id=settings.channel_id,
                text=truncate_to_message(text),
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        else:
            # Нет нашей картинки. Фолбэк: текст + Telegram link-preview.
            sent = await bot.send_message(
                chat_id=settings.channel_id,
                text=truncate_to_message(text),
                link_preview_options=LinkPreviewOptions(
                    url=draft.primary_source_url,
                    prefer_large_media=True,
                    show_above_text=True,
                ),
            )
    except Exception as e:  # noqa: BLE001
        logger.exception("Publish failed")
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

    await cq.answer("Генерирую заново…")
    await _strip_keyboard(cq)

    status = await cq.message.answer("Ищу другой инфоповод…")

    # помечаем текущий черновик rejected ДО генерации, чтобы его заголовок
    # тоже попал в exclude_topics
    await repo.mark_rejected(draft_id)

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
    await _send_preview(cq.message, result)


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

    await repo.mark_rejected(draft_id)
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
    if not refreshed:
        return

    await _send_raw_preview(
        message,
        draft_id=draft_id,
        text=refreshed.formatted_text,
        image_file_id=refreshed.image_file_id,
        primary_source_url=refreshed.primary_source_url,
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


async def _send_preview(message: Message, draft: PostDraft) -> None:
    """Сохраняет черновик в БД, шлёт превью владельцу.

    Перебирает primary_source_url + extra_sources в поисках лучшего og:image
    (не логотипа). Картинку загружаем в Telegram, сохраняем file_id, чтобы
    Approve переиспользовал тот же кадр без повторной выкачки.
    """
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

    new_file_id = await _do_send_preview(
        message=message,
        draft_id=draft_id,
        text=formatted,
        image_bytes=fetched.content if fetched else None,
        image_file_id=None,
        primary_source_url=str(draft.primary_source_url),
    )
    if new_file_id:
        await repo.set_image_file_id(draft_id, new_file_id)


async def _send_raw_preview(
    message: Message,
    *,
    draft_id: int,
    text: str,
    image_file_id: str | None,
    primary_source_url: str,
) -> None:
    await _do_send_preview(
        message=message,
        draft_id=draft_id,
        text=text,
        image_bytes=None,
        image_file_id=image_file_id,
        primary_source_url=primary_source_url,
    )


async def _do_send_preview(
    *,
    message: Message,
    draft_id: int,
    text: str,
    image_bytes: bytes | None,
    image_file_id: str | None,
    primary_source_url: str,
) -> str | None:
    """Шлёт превью. Возвращает file_id, если впервые загружали байты картинки.

    Главный путь: одно сообщение photo+caption (если есть картинка и текст
    влезает в caption-лимит). Если картинки нет — текст + link-preview.
    Если caption переполнен — предупреждаем и фолбэчим на 2 сообщения.
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
        m = await message.answer_photo(photo=photo, caption=text, reply_markup=kb)
        return m.photo[-1].file_id if fresh_upload and m.photo else None

    if photo is not None:
        # caption переполнен — это уже аномалия (модель нарушила лимит).
        logger.warning("Caption > 1024 ({}), splitting preview", len(text))
        m = await message.answer_photo(photo=photo)
        new_file_id = m.photo[-1].file_id if fresh_upload and m.photo else None
        await message.answer(
            text=truncate_to_message(text),
            reply_markup=kb,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return new_file_id

    # Нет картинки вообще — фолбэк на link-preview
    await message.answer(
        text=truncate_to_message(text),
        reply_markup=kb,
        link_preview_options=LinkPreviewOptions(
            url=primary_source_url,
            prefer_large_media=True,
            show_above_text=True,
        ),
    )
    return None
