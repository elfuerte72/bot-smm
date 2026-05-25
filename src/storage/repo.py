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


# ──────────────────────────────────────────────────────────────────────────────
# Audit events на драфтах (Task 2 spec): created/edited/regenerated_from/
# approved/rejected. Payload-форма зафиксирована в docs/spec/mini-app.md.
# ──────────────────────────────────────────────────────────────────────────────


async def record_draft_event(
    draft_id: int,
    event_type: str,
    *,
    actor_user_id: int | None,
    payload: dict[str, object] | None = None,
) -> int:
    """Пишет одну строку в draft_events. Возвращает id записи.

    actor_user_id=None означает событие от cron/системы.
    payload сериализуется в JSON (ensure_ascii=False — русский читаемо в SELECT).
    """
    body = json.dumps(payload or {}, ensure_ascii=False)
    async with get_conn() as conn:
        cur = await conn.execute(
            """
            INSERT INTO draft_events (draft_id, event_type, actor_user_id, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (draft_id, event_type, actor_user_id, body),
        )
        await conn.commit()
        return cur.lastrowid or 0


# ──────────────────────────────────────────────────────────────────────────────
# Реакции на опубликованные посты (Task 3 spec).
# ──────────────────────────────────────────────────────────────────────────────


async def upsert_post_reactions(
    *,
    tg_message_id: int,
    channel_id: str,
    total_count: int,
    reactions: list[dict[str, object]],
) -> None:
    """Идемпотентный upsert агрегата реакций по (tg_message_id, channel_id).

    Telegram присылает MessageReactionCountUpdated со снапшотом текущих
    счётчиков, поэтому всегда перезаписываем total_count/reactions_json
    целиком, не инкрементально.
    """
    body = json.dumps(reactions, ensure_ascii=False)
    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO post_reactions (tg_message_id, channel_id, total_count, reactions_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(tg_message_id, channel_id) DO UPDATE SET
                total_count = excluded.total_count,
                reactions_json = excluded.reactions_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (tg_message_id, channel_id, total_count, body),
        )
        await conn.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Снапшоты подписчиков (Task 4 spec, функция готова заранее, чтобы не дробить
# repo.py по таскам; вызывать её начнёт scheduler в Task 4).
# ──────────────────────────────────────────────────────────────────────────────


async def add_channel_snapshot(*, channel_id: str, member_count: int) -> None:
    async with get_conn() as conn:
        await conn.execute(
            "INSERT INTO channel_snapshots (channel_id, member_count) VALUES (?, ?)",
            (channel_id, member_count),
        )
        await conn.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Чтения для Mini App API (Task 6 spec).
# ──────────────────────────────────────────────────────────────────────────────


_PERIOD_TO_SQLITE = {
    "24h": "-1 day",
    "7d": "-7 day",
    "30d": "-30 day",
}


def _period_clause(period: str) -> str | None:
    """Возвращает SQLite-выражение для clause `created_at >= datetime(...)`
    или None для 'all' / неизвестных значений (фолбэк → без фильтра)."""
    if period == "all":
        return None
    return _PERIOD_TO_SQLITE.get(period)


_VALID_STATUSES: tuple[str, ...] = ("draft", "publishing", "published", "rejected")


async def posts_stats() -> dict[str, int]:
    """Возвращает counts по статусам + total. Используется /api/posts/stats.

    Порядок ключей в ответе детерминированный — `_VALID_STATUSES` кортеж,
    не set: фронт может полагаться на порядок (хотя сейчас сортирует сам).
    """
    counts: dict[str, int] = {s: 0 for s in _VALID_STATUSES}
    async with get_conn() as conn:
        async with conn.execute(
            "SELECT status, COUNT(*) FROM drafts GROUP BY status"
        ) as cur:
            async for row in cur:
                counts[str(row[0])] = int(row[1])
    counts["total"] = sum(counts.values())
    return counts


async def list_posts(
    *,
    status: str | None,
    period: str,
    search: str | None,
    offset: int,
    limit: int,
) -> tuple[list[dict[str, object]], int]:
    """Постраничный список постов с фильтрами. Возвращает (items, total).

    Все параметры биндятся как `?`-плейсхолдеры — никаких форматных подстановок.
    Поиск делается по `json_extract(drafts.raw_json, '$.title')` (для черновиков)
    И по `published.title` (для уже опубликованных). LIKE с COLLATE NOCASE —
    case-insensitive в ASCII; русский UTF-8 матчится через подстроку дословно.
    """
    where: list[str] = []
    params: list[object] = []
    if status and status in _VALID_STATUSES:
        where.append("d.status = ?")
        params.append(status)

    period_expr = _period_clause(period)
    if period_expr is not None:
        where.append("d.created_at >= datetime('now', ?)")
        params.append(period_expr)

    if search:
        like = f"%{search.strip()}%"
        where.append(
            "(COALESCE(json_extract(d.raw_json, '$.title'), '') LIKE ? COLLATE NOCASE"
            " OR COALESCE(p.title, '') LIKE ? COLLATE NOCASE)"
        )
        params.extend([like, like])

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    # GROUP BY d.id защищает от дубликации, если у одного draft почему-то
    # окажется >1 строки в `published` (FK без UNIQUE на draft_id — латентный
    # риск). MIN/MAX для скаляров и MAX для total_count — нейтральные агрегаты:
    # в normal flow это один-к-одному, и MIN==MAX==единственное значение.
    select_sql = f"""
        SELECT
            d.id,
            d.created_at,
            d.status,
            d.primary_source_url,
            json_extract(d.raw_json, '$.title') AS draft_title,
            d.formatted_text,
            MIN(p.tg_message_id) AS tg_message_id,
            MIN(p.published_at) AS published_at,
            MIN(p.title) AS published_title,
            MAX(pr.total_count) AS total_reactions
        FROM drafts d
        LEFT JOIN published p ON p.draft_id = d.id
        LEFT JOIN post_reactions pr ON pr.tg_message_id = p.tg_message_id
        {where_sql}
        GROUP BY d.id
        ORDER BY d.created_at DESC
        LIMIT ? OFFSET ?
    """
    # COUNT(DISTINCT d.id) парная защита: даже если JOIN надувает строки,
    # COUNT(*) дал бы завышенный total — DISTINCT сводит к числу уникальных
    # драфтов, проходящих под фильтры.
    count_sql = f"""
        SELECT COUNT(DISTINCT d.id)
        FROM drafts d
        LEFT JOIN published p ON p.draft_id = d.id
        {where_sql}
    """

    items: list[dict[str, object]] = []
    async with get_conn() as conn:
        async with conn.execute(select_sql, [*params, limit, offset]) as cur:
            async for row in cur:
                items.append(_row_to_post(row))
        async with conn.execute(count_sql, params) as cur:
            r = await cur.fetchone()
            total = int(r[0]) if r else 0

    return items, total


def _row_to_post(row: tuple[object, ...]) -> dict[str, object]:
    """Мап-функция из SQL-строки list_posts/get_post_detail в JSON-friendly dict."""
    (
        draft_id,
        created_at,
        status,
        primary_source_url,
        draft_title,
        formatted_text,
        tg_message_id,
        published_at,
        published_title,
        total_reactions,
    ) = row
    title = (published_title or draft_title or "(без заголовка)").strip()
    formatted = str(formatted_text or "")
    preview = formatted[:200] + ("…" if len(formatted) > 200 else "")
    return {
        "id": int(draft_id) if draft_id is not None else 0,
        "created_at": str(created_at) if created_at else None,
        "status": str(status) if status else None,
        "title": title,
        "preview": preview,
        "primary_source_url": str(primary_source_url) if primary_source_url else None,
        "tg_message_id": int(tg_message_id) if tg_message_id is not None else None,
        "published_at": str(published_at) if published_at else None,
        "total_reactions": int(total_reactions) if total_reactions is not None else None,
    }


async def get_post_detail(draft_id: int) -> dict[str, object] | None:
    """Полная карточка поста: draft + events[] + published? + reactions?.

    Возвращает None, если draft с таким id не найден.
    """
    async with get_conn() as conn:
        async with conn.execute(
            """
            SELECT
                d.id,
                d.created_at,
                d.status,
                d.primary_source_url,
                json_extract(d.raw_json, '$.title') AS draft_title,
                d.formatted_text,
                p.tg_message_id,
                p.published_at,
                p.title AS published_title,
                pr.total_count
            FROM drafts d
            LEFT JOIN published p ON p.draft_id = d.id
            LEFT JOIN post_reactions pr ON pr.tg_message_id = p.tg_message_id
            WHERE d.id = ?
            """,
            (draft_id,),
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            post = _row_to_post(row)

        events: list[dict[str, object]] = []
        async with conn.execute(
            """
            SELECT id, event_type, actor_user_id, created_at, payload_json
            FROM draft_events
            WHERE draft_id = ?
            ORDER BY id ASC
            """,
            (draft_id,),
        ) as cur:
            async for ev in cur:
                payload: object
                try:
                    payload = json.loads(ev[4]) if ev[4] else {}
                except json.JSONDecodeError:
                    payload = {}
                events.append(
                    {
                        "id": int(ev[0]),
                        "event_type": str(ev[1]),
                        "actor_user_id": int(ev[2]) if ev[2] is not None else None,
                        "created_at": str(ev[3]) if ev[3] else None,
                        "payload": payload,
                    }
                )

        reactions: dict[str, object] | None = None
        tg_message_id = post.get("tg_message_id")
        if tg_message_id is not None:
            async with conn.execute(
                """
                SELECT total_count, reactions_json, updated_at
                FROM post_reactions
                WHERE tg_message_id = ?
                """,
                (tg_message_id,),
            ) as cur:
                r = await cur.fetchone()
                if r is not None:
                    try:
                        breakdown = json.loads(r[1]) if r[1] else []
                    except json.JSONDecodeError:
                        breakdown = []
                    reactions = {
                        "total_count": int(r[0]),
                        "reactions": breakdown,
                        "updated_at": str(r[2]) if r[2] else None,
                    }

    return {"post": post, "events": events, "reactions": reactions}


async def channel_snapshots(*, channel_id: str, days: int = 7) -> list[dict[str, object]]:
    """Возвращает точки sparkline за N дней (ASC по ts — для прямой отрисовки)."""
    async with get_conn() as conn:
        async with conn.execute(
            """
            SELECT ts, member_count
            FROM channel_snapshots
            WHERE channel_id = ?
              AND ts >= datetime('now', ?)
            ORDER BY ts ASC
            """,
            (channel_id, f"-{int(days)} day"),
        ) as cur:
            return [
                {"ts": str(row[0]), "member_count": int(row[1])}
                async for row in cur
            ]


async def latest_member_count(channel_id: str) -> int | None:
    """Последнее известное значение member_count из channel_snapshots."""
    async with get_conn() as conn:
        async with conn.execute(
            """
            SELECT member_count FROM channel_snapshots
            WHERE channel_id = ? ORDER BY ts DESC LIMIT 1
            """,
            (channel_id,),
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else None


async def top_reactions(*, limit: int = 10) -> list[dict[str, object]]:
    """Топ постов по total_count DESC. Только опубликованные посты с реакциями."""
    return await _reactions_list("DESC", limit=limit, min_age_hours=0)


async def bottom_reactions(*, limit: int = 10) -> list[dict[str, object]]:
    """Анти-топ постов по total_count ASC. Учитываем только опубликованные ≥ 24ч
    назад: иначе свежие посты с 0 реакций забили бы выдачу."""
    return await _reactions_list("ASC", limit=limit, min_age_hours=24)


async def _reactions_list(
    order: str, *, limit: int, min_age_hours: int
) -> list[dict[str, object]]:
    if order not in {"ASC", "DESC"}:
        # Защита от случайного inject — никогда не должно случиться, всё внутри.
        raise ValueError(f"bad order: {order}")
    sql = f"""
        SELECT
            pr.tg_message_id,
            pr.channel_id,
            pr.total_count,
            pr.reactions_json,
            pr.updated_at,
            p.title,
            p.published_at,
            p.draft_id
        FROM post_reactions pr
        INNER JOIN published p ON p.tg_message_id = pr.tg_message_id
        WHERE p.published_at <= datetime('now', ?)
        ORDER BY pr.total_count {order}
        LIMIT ?
    """
    age_expr = f"-{int(min_age_hours)} hour"
    async with get_conn() as conn:
        async with conn.execute(sql, (age_expr, limit)) as cur:
            rows = await cur.fetchall()

    out: list[dict[str, object]] = []
    for row in rows:
        try:
            breakdown = json.loads(row[3]) if row[3] else []
        except json.JSONDecodeError:
            breakdown = []
        out.append(
            {
                "tg_message_id": int(row[0]),
                "channel_id": str(row[1]),
                "total_count": int(row[2]),
                "reactions": breakdown,
                "updated_at": str(row[4]) if row[4] else None,
                "title": str(row[5]) if row[5] else "(без заголовка)",
                "published_at": str(row[6]) if row[6] else None,
                "draft_id": int(row[7]) if row[7] is not None else None,
            }
        )
    return out
