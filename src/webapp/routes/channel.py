from __future__ import annotations

from fastapi import APIRouter, Query

from src.config import settings
from src.storage import repo
from src.webapp.deps import CurrentUser

router = APIRouter()


@router.get("/channel/stats")
async def channel_stats(
    user: CurrentUser,
    days: int = Query(default=7, ge=1, le=30),
) -> dict[str, object]:
    """Текущий member_count + sparkline-snapshots за N дней (default 7).

    title подтягивается из ``app_settings['channel_title']`` — кешируется
    каждый snapshot job через get_chat.title. Если ещё не сохранён, отдаём
    пустую строку, фронт фолбэкается на channel_id.
    """
    channel_id = str(settings.channel_id)
    snapshots = await repo.channel_snapshots(channel_id=channel_id, days=days)
    member_count = await repo.latest_member_count(channel_id)
    title = await repo.get_setting("channel_title", "") or ""
    return {
        "channel_id": channel_id,
        "title": title,
        "member_count": member_count,
        "snapshots": snapshots,
        "days": days,
    }
