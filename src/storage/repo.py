from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.storage.db import get_conn


@dataclass(slots=True)
class DraftRow:
    id: int
    raw_json: str
    formatted_text: str
    image_url: str | None
    image_file_id: str | None
    primary_source_url: str
    status: str


async def save_draft(
    *,
    raw_json: str,
    formatted_text: str,
    image_url: str | None,
    primary_source_url: str,
) -> int:
    async with get_conn() as conn:
        cur = await conn.execute(
            """
            INSERT INTO drafts (raw_json, formatted_text, image_url, primary_source_url, status)
            VALUES (?, ?, ?, ?, 'draft')
            """,
            (raw_json, formatted_text, image_url, primary_source_url),
        )
        await conn.commit()
        return cur.lastrowid or 0


async def set_image_file_id(draft_id: int, file_id: str) -> None:
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE drafts SET image_file_id = ? WHERE id = ?",
            (file_id, draft_id),
        )
        await conn.commit()


async def get_draft(draft_id: int) -> DraftRow | None:
    async with get_conn() as conn:
        async with conn.execute(
            """
            SELECT id, raw_json, formatted_text, image_url, image_file_id,
                   primary_source_url, status
            FROM drafts WHERE id = ?
            """,
            (draft_id,),
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            return DraftRow(
                id=row[0],
                raw_json=row[1],
                formatted_text=row[2],
                image_url=row[3],
                image_file_id=row[4],
                primary_source_url=row[5],
                status=row[6],
            )


async def update_draft_text(draft_id: int, formatted_text: str) -> None:
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE drafts SET formatted_text = ? WHERE id = ?",
            (formatted_text, draft_id),
        )
        # синхронизируем raw_json.body
        async with conn.execute(
            "SELECT raw_json FROM drafts WHERE id = ?", (draft_id,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            try:
                data = json.loads(row[0])
                data["_edited_text"] = formatted_text
                await conn.execute(
                    "UPDATE drafts SET raw_json = ? WHERE id = ?",
                    (json.dumps(data, ensure_ascii=False), draft_id),
                )
            except json.JSONDecodeError:
                pass
        await conn.commit()


async def claim_for_publish(draft_id: int) -> bool:
    """Атомарный захват черновика для публикации: draft → publishing.

    Возвращает True только если статус был 'draft' и удалось перевести в
    'publishing'. Защищает от двойной публикации, когда превью разослано
    нескольким получателям (cron-сценарий).
    """
    async with get_conn() as conn:
        cur = await conn.execute(
            "UPDATE drafts SET status = 'publishing' WHERE id = ? AND status = 'draft'",
            (draft_id,),
        )
        await conn.commit()
        return cur.rowcount == 1


async def release_publish(draft_id: int) -> None:
    """Откат захвата при ошибке отправки в канал: publishing → draft."""
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE drafts SET status = 'draft' WHERE id = ? AND status = 'publishing'",
            (draft_id,),
        )
        await conn.commit()


async def mark_published(draft_id: int, *, source_url: str, title: str, tg_message_id: int) -> None:
    async with get_conn() as conn:
        await conn.execute("UPDATE drafts SET status = 'published' WHERE id = ?", (draft_id,))
        await conn.execute(
            """
            INSERT OR IGNORE INTO published (draft_id, source_url, title, tg_message_id)
            VALUES (?, ?, ?, ?)
            """,
            (draft_id, source_url, title, tg_message_id),
        )
        await conn.commit()


async def mark_rejected(draft_id: int) -> bool:
    """Атомарный переход draft → rejected. Возвращает True, если захватили."""
    async with get_conn() as conn:
        cur = await conn.execute(
            "UPDATE drafts SET status = 'rejected' WHERE id = ? AND status = 'draft'",
            (draft_id,),
        )
        await conn.commit()
        return cur.rowcount == 1


async def recent_source_urls(*, days: int = 14, limit: int = 50) -> list[str]:
    """URL опубликованных и черновиковых новостей за последние N дней — для exclude-списка."""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    async with get_conn() as conn:
        async with conn.execute(
            """
            SELECT source_url FROM published WHERE published_at >= ?
            UNION
            SELECT primary_source_url FROM drafts WHERE created_at >= ?
            ORDER BY 1
            LIMIT ?
            """,
            (since, since, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows if r[0]]


async def recent_topics(*, days: int = 7, limit: int = 30) -> list[str]:
    """Заголовки недавних постов и черновиков. Используется, чтобы агент не писал
    про одну и ту же новость, даже если у неё другой URL (другое издание)."""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    titles: list[str] = []
    async with get_conn() as conn:
        async with conn.execute(
            """
            SELECT title FROM published
            WHERE published_at >= ?
            ORDER BY published_at DESC
            LIMIT ?
            """,
            (since, limit),
        ) as cur:
            async for row in cur:
                if row[0]:
                    titles.append(row[0])

        async with conn.execute(
            """
            SELECT raw_json FROM drafts
            WHERE created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (since, limit),
        ) as cur:
            async for row in cur:
                try:
                    data = json.loads(row[0])
                    t = data.get("title")
                    if isinstance(t, str) and t and t not in titles:
                        titles.append(t)
                except json.JSONDecodeError:
                    continue

    return titles[:limit]
