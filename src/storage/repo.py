from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher

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


async def record_api_usage(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    cost_usd: float = 0.0,
) -> None:
    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO api_usage (
                model, input_tokens, output_tokens,
                cache_creation_tokens, cache_read_tokens, cost_usd
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                model,
                input_tokens,
                output_tokens,
                cache_creation_tokens,
                cache_read_tokens,
                cost_usd,
            ),
        )
        await conn.commit()


async def usage_summary() -> dict[str, dict[str, float | int]]:
    """Возвращает агрегаты {today, month, total} по локальной TZ SQLite (UTC)."""
    queries = {
        "today": (
            "SELECT COALESCE(SUM(cost_usd),0), COUNT(*) FROM api_usage "
            "WHERE date(ts)=date('now')"
        ),
        "week": (
            "SELECT COALESCE(SUM(cost_usd),0), COUNT(*) FROM api_usage "
            "WHERE date(ts) >= date('now','-6 days')"
        ),
        "month": (
            "SELECT COALESCE(SUM(cost_usd),0), COUNT(*) FROM api_usage "
            "WHERE strftime('%Y-%m', ts)=strftime('%Y-%m','now')"
        ),
        "total": "SELECT COALESCE(SUM(cost_usd),0), COUNT(*) FROM api_usage",
    }
    out: dict[str, dict[str, float | int]] = {}
    async with get_conn() as conn:
        for key, sql in queries.items():
            async with conn.execute(sql) as cur:
                r = await cur.fetchone()
                out[key] = {"usd": float(r[0] or 0.0), "calls": int(r[1] or 0)}
    return out


async def usage_by_day(*, days: int = 7) -> list[dict[str, float | int | str]]:
    """Возвращает по дням за последние N дней (включая сегодня), в порядке DESC."""
    sql = (
        "SELECT date(ts) AS d, COALESCE(SUM(cost_usd),0), COUNT(*) "
        "FROM api_usage WHERE date(ts) >= date('now', ?) "
        "GROUP BY d ORDER BY d DESC"
    )
    delta = f"-{days - 1} days"
    async with get_conn() as conn:
        async with conn.execute(sql, (delta,)) as cur:
            rows = await cur.fetchall()
    return [{"date": r[0], "usd": float(r[1]), "calls": int(r[2])} for r in rows]


async def get_setting(key: str, default: str | None = None) -> str | None:
    async with get_conn() as conn:
        async with conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else default


async def set_setting(key: str, value: str) -> None:
    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        await conn.commit()


async def get_cron_times() -> list[str] | None:
    """Возвращает список HH:MM или None, если в БД ничего нет (нужен seed)."""
    raw = await get_setting("cron_times")
    if raw is None:
        return None
    return [x.strip() for x in raw.split(",") if x.strip()]


async def set_cron_times(times: list[str]) -> None:
    await set_setting("cron_times", ",".join(times))


async def _recent_titles(*, days: int, limit: int) -> list[str]:
    """Заголовки опубликованных постов и черновиков за последние N дней."""
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

    return titles


async def recent_topics(*, days: int = 7, limit: int = 30) -> list[str]:
    """Заголовки недавних постов и черновиков. Используется, чтобы агент не писал
    про одну и ту же новость, даже если у неё другой URL (другое издание)."""
    titles = await _recent_titles(days=days, limit=limit)
    return titles[:limit]


def _normalize_title(text: str) -> str:
    """Нижний регистр, только буквы/цифры/пробелы — для сравнения тем."""
    return re.sub(r"[^0-9a-zа-яё ]+", " ", text.lower()).strip()


async def find_similar_topics(headline: str, *, days: int = 14, limit: int = 5) -> list[str]:
    """Жёсткая проверка дублей: ищет среди недавних заголовков похожие на headline.

    Используется client tool check_topic_covered: агент проверяет найденный
    инфоповод до отправки поста. Совпадением считаем высокий
    SequenceMatcher.ratio либо заметное пересечение значимых слов (двойная
    защита: ratio ловит перефразировки, пересечение слов — разный порядок).
    """
    headline_norm = _normalize_title(headline)
    if not headline_norm:
        return []
    headline_words = {w for w in headline_norm.split() if len(w) > 3}

    matches: list[str] = []
    for title in await _recent_titles(days=days, limit=50):
        title_norm = _normalize_title(title)
        if not title_norm:
            continue
        ratio = SequenceMatcher(None, headline_norm, title_norm).ratio()
        title_words = {w for w in title_norm.split() if len(w) > 3}
        overlap = len(headline_words & title_words) / len(headline_words) if headline_words else 0.0
        if ratio >= 0.6 or overlap >= 0.6:
            matches.append(title)
        if len(matches) >= limit:
            break

    return matches
