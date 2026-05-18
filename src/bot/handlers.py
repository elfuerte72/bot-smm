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
    Message,
)
from loguru import logger

from src.agent.news_agent import AgentError, generate_post
from src.agent.schemas import NoNews, PostDraft
from src.bot.keyboards import edit_cancel_keyboard, preview_keyboard
from src.config import settings
from src.media.og_image import FetchedImage, fetch_og_image
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
        exclude = await repo.recent_source_urls()
        result = await generate_post(exclude_urls=exclude)
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
    image_bytes = await _maybe_download(draft.image_url)

    try:
        if image_bytes and fits_caption(text):
            sent = await bot.send_photo(
                chat_id=settings.channel_id,
                photo=BufferedInputFile(image_bytes, filename="cover.jpg"),
                caption=text,
            )
        elif image_bytes:
            await bot.send_photo(
                chat_id=settings.channel_id,
                photo=BufferedInputFile(image_bytes, filename="cover.jpg"),
            )
            sent = await bot.send_message(
                chat_id=settings.channel_id,
                text=truncate_to_message(text),
                disable_web_page_preview=False,
            )
        else:
            sent = await bot.send_message(
                chat_id=settings.channel_id,
                text=truncate_to_message(text),
                disable_web_page_preview=False,
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
    try:
        exclude = await repo.recent_source_urls()
        # на всякий случай прибавим текущий
        if draft.primary_source_url not in exclude:
            exclude.append(draft.primary_source_url)
        result = await generate_post(exclude_urls=exclude)
    except AgentError as e:
        await status.edit_text(f"Не получилось перегенерировать: {e}")
        return

    await repo.mark_rejected(draft_id)

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
        image_url=refreshed.image_url,
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


async def _maybe_download(image_url: str | None) -> bytes | None:
    if not image_url:
        return None
    fetched: FetchedImage | None = await fetch_og_image(image_url)
    return fetched.content if fetched else None


async def _send_preview(message: Message, draft: PostDraft) -> None:
    """Сохраняет черновик в БД, скачивает картинку, шлёт превью с кнопками."""
    formatted = format_post(draft)

    fetched = await fetch_og_image(str(draft.primary_source_url))
    image_url = fetched.url if fetched else None

    draft_id = await repo.save_draft(
        raw_json=json.dumps(draft.model_dump(mode="json"), ensure_ascii=False),
        formatted_text=formatted,
        image_url=image_url,
        primary_source_url=str(draft.primary_source_url),
    )

    await _do_send_preview(
        message=message,
        draft_id=draft_id,
        text=formatted,
        image_bytes=fetched.content if fetched else None,
    )


async def _send_raw_preview(
    message: Message,
    *,
    draft_id: int,
    text: str,
    image_url: str | None,
) -> None:
    image_bytes = await _maybe_download(image_url)
    await _do_send_preview(
        message=message,
        draft_id=draft_id,
        text=text,
        image_bytes=image_bytes,
    )


async def _do_send_preview(
    *,
    message: Message,
    draft_id: int,
    text: str,
    image_bytes: bytes | None,
) -> None:
    kb: InlineKeyboardMarkup = preview_keyboard(draft_id)

    if image_bytes and fits_caption(text):
        await message.answer_photo(
            photo=BufferedInputFile(image_bytes, filename="cover.jpg"),
            caption=text,
            reply_markup=kb,
        )
        return

    if image_bytes:
        await message.answer_photo(
            photo=BufferedInputFile(image_bytes, filename="cover.jpg"),
        )

    await message.answer(
        text=truncate_to_message(text),
        reply_markup=kb,
        disable_web_page_preview=False,
    )
