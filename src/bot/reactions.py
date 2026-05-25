from __future__ import annotations

from aiogram import Router
from aiogram.types import MessageReactionCountUpdated
from loguru import logger

from src.config import settings
from src.storage import repo

router = Router()


def _is_target_channel(event: MessageReactionCountUpdated) -> bool:
    """Реакции пишем только из канала из настроек.

    settings.channel_id может быть числовым id (`-1001234...`) или username
    (`@channel`). Telegram присылает event.chat.id (числовой) и опционально
    event.chat.username. Сравниваем обе формы — что подходит, то и считаем
    нашим каналом.
    """
    expected = str(settings.channel_id)
    if expected == str(event.chat.id):
        return True
    if event.chat.username and expected == f"@{event.chat.username}":
        return True
    return False


def _serialize_reactions(event: MessageReactionCountUpdated) -> list[dict[str, object]]:
    """Преобразует aiogram-объекты reactions в plain dict для JSON-хранения.

    Поддерживает два варианта типа реакции: стандартный emoji и custom_emoji.
    Для custom emoji в поле "emoji" кладём id, отдельным ключом "type"
    помечаем источник, чтобы UI потом мог это различить.
    """
    out: list[dict[str, object]] = []
    for rc in event.reactions:
        rtype = getattr(rc.type, "type", None)
        if rtype == "emoji":
            out.append(
                {
                    "type": "emoji",
                    "emoji": getattr(rc.type, "emoji", ""),
                    "count": rc.total_count,
                }
            )
        elif rtype == "custom_emoji":
            out.append(
                {
                    "type": "custom_emoji",
                    "emoji": getattr(rc.type, "custom_emoji_id", ""),
                    "count": rc.total_count,
                }
            )
        else:
            # Будущий неизвестный тип — пишем raw, не теряем счётчик.
            out.append({"type": str(rtype), "emoji": "", "count": rc.total_count})
    return out


@router.message_reaction_count()
async def on_message_reaction_count(event: MessageReactionCountUpdated) -> None:
    """Анонимная сводка реакций на канал-пост: пишем снапшот в post_reactions.

    Telegram присылает агрегаты (а не дельты), поэтому upsert полностью
    перезаписывает строку. Если бот ещё не админ канала или allowed_updates
    не содержит message_reaction_count, этот хендлер просто не вызовется.

    OwnerOnlyMiddleware не покрывает message_reaction_count observer (он
    только на dp.message/dp.callback_query), и у event нет from_user.
    Авторизация здесь — фильтр по chat.id канала из settings.
    """
    if not _is_target_channel(event):
        logger.debug(
            "reactions: ignore foreign chat id={} username={}",
            event.chat.id,
            event.chat.username,
        )
        return

    reactions = _serialize_reactions(event)
    total = sum(int(r["count"]) for r in reactions)

    await repo.upsert_post_reactions(
        tg_message_id=event.message_id,
        channel_id=str(event.chat.id),
        total_count=total,
        reactions=reactions,
    )
    logger.debug(
        "reactions upsert: chat={} msg={} total={} reactions={}",
        event.chat.id,
        event.message_id,
        total,
        reactions,
    )
