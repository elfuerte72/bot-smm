from __future__ import annotations

from aiogram import Router
from aiogram.types import MessageReactionCountUpdated
from loguru import logger

from src.storage import repo

router = Router()


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
    """
    reactions = _serialize_reactions(event)
    total = sum(int(r.get("count", 0) or 0) for r in reactions)
    channel_id = str(event.chat.id)

    await repo.upsert_post_reactions(
        tg_message_id=event.message_id,
        channel_id=channel_id,
        total_count=total,
        reactions=reactions,
    )
    logger.debug(
        "reactions upsert: chat={} msg={} total={} reactions={}",
        channel_id,
        event.message_id,
        total,
        reactions,
    )
