"""Бэкфилл архива канала из экспорта Telegram Desktop (result.json).

Использование:
    uv run python scripts/backfill_from_tg_export.py \\
        --input ./data/aibromotion_export.json \\
        --channel-username aibromotion \\
        [--dry-run] [--limit N]

Telegram Desktop → Settings → Advanced → Export Telegram data → выбрать только
нужный канал → format JSON, без медиа → положить result.json в ./data/.

Скрипт идемпотентен: уже импортированные сообщения (по published.tg_message_id)
пропускаются. Пишет напрямую в drafts + published со status='published',
минуя публикационную логику бота. Реакции и медиа не импортирует.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

# Скрипт лежит вне src/ — добавим корень в sys.path, чтобы импорты src.* работали.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.storage.db import get_conn, init_db  # noqa: E402
from src.storage.text_utils import html_to_plain  # noqa: E402


def entities_to_html(text: str, entities: list[dict]) -> str:
    """Конвертация text_entities из TG Desktop в Telegram-HTML.

    Telegram Desktop кладёт сегментированный текст: каждый entity — кусок строки
    с типом форматирования. Поддерживаемые типы перечислены ниже; неизвестные
    типы (mention_name, custom_emoji, hashtag и пр.) выводим как plain.
    """
    if not entities:
        return html.escape(text)
    parts: list[str] = []
    for e in entities:
        t = e.get("type", "plain")
        raw = e.get("text", "")
        esc = html.escape(raw)
        if t == "plain":
            parts.append(esc)
        elif t == "bold":
            parts.append(f"<b>{esc}</b>")
        elif t == "italic":
            parts.append(f"<i>{esc}</i>")
        elif t == "underline":
            parts.append(f"<u>{esc}</u>")
        elif t == "strikethrough":
            parts.append(f"<s>{esc}</s>")
        elif t == "code":
            parts.append(f"<code>{esc}</code>")
        elif t == "pre":
            parts.append(f"<pre>{esc}</pre>")
        elif t == "blockquote":
            parts.append(f"<blockquote>{esc}</blockquote>")
        elif t == "spoiler":
            parts.append(f"<tg-spoiler>{esc}</tg-spoiler>")
        elif t == "text_link":
            href = html.escape(e.get("href", ""), quote=True)
            parts.append(f'<a href="{href}">{esc}</a>')
        elif t == "link":
            href = html.escape(raw, quote=True)
            parts.append(f'<a href="{href}">{esc}</a>')
        elif t == "mention":
            uname = raw.lstrip("@")
            parts.append(f'<a href="https://t.me/{uname}">{esc}</a>')
        else:
            parts.append(esc)
    return "".join(parts)


def extract_title(entities: list[dict], plain_body: str, msg_date: str) -> str:
    """Эвристика: bold-зачин → первая строка → fallback по дате."""
    for e in entities or []:
        if e.get("type") == "bold":
            candidate = (e.get("text") or "").strip()
            if 5 <= len(candidate) <= 120:
                return candidate[:90]
            break
    first_line = plain_body.split("\n", 1)[0].strip() if plain_body else ""
    if first_line:
        return first_line[:90] + ("…" if len(first_line) > 90 else "")
    try:
        d = datetime.fromisoformat(msg_date).strftime("%Y-%m-%d")
    except ValueError:
        d = msg_date[:10] if msg_date else ""
    return f"Архивный пост от {d}" if d else "Архивный пост"


def first_url_from_entities(entities: list[dict]) -> str | None:
    for e in entities or []:
        t = e.get("type")
        if t == "text_link":
            href = e.get("href")
            if href:
                return str(href)
        elif t == "link":
            txt = e.get("text")
            if txt:
                return str(txt)
    return None


def normalize_text(raw_text: object) -> tuple[str, list[dict]]:
    """TG Desktop кладёт text как str или как list[entity-like|str].

    Старые экспорты — list, новые — str. Если list, можно склеить и
    восстановить entities из него же.
    """
    if isinstance(raw_text, str):
        return raw_text, []
    if isinstance(raw_text, list):
        text_parts: list[str] = []
        entities: list[dict] = []
        for item in raw_text:
            if isinstance(item, str):
                text_parts.append(item)
                entities.append({"type": "plain", "text": item})
            elif isinstance(item, dict):
                t = str(item.get("text", ""))
                text_parts.append(t)
                entities.append(item)
        return "".join(text_parts), entities
    return "", []


def to_sqlite_ts(iso: str) -> str:
    """Привести ISO-дату из экспорта к формату SQLite CURRENT_TIMESTAMP."""
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return iso


async def import_messages(
    *,
    messages: list[dict],
    channel_username: str,
    dry_run: bool,
    limit: int | None,
) -> None:
    logger.info("Processing {} messages", len(messages))

    await init_db()

    imported = 0
    skipped_existing = 0
    skipped_empty = 0
    errors = 0
    preview_shown = 0

    async with get_conn() as conn:
        for msg in messages:
            if limit is not None and imported + skipped_existing >= limit:
                break

            raw_text = msg.get("text")
            text, derived_entities = normalize_text(raw_text)
            entities = msg.get("text_entities") or derived_entities
            if not text.strip() and not entities:
                skipped_empty += 1
                continue

            try:
                msg_id = int(msg["id"])
            except (KeyError, ValueError, TypeError):
                errors += 1
                continue

            # Идемпотентность: посты с этим tg_message_id уже импортированы.
            async with conn.execute(
                "SELECT id FROM published WHERE tg_message_id = ? LIMIT 1",
                (msg_id,),
            ) as cur:
                if await cur.fetchone() is not None:
                    skipped_existing += 1
                    continue

            formatted_html = entities_to_html(text, entities)
            plain_body = html_to_plain(formatted_html)
            title = extract_title(entities, plain_body, msg.get("date", ""))
            first_url = first_url_from_entities(entities)
            tg_url = f"https://t.me/{channel_username}/{msg_id}"
            source_url = first_url or tg_url
            created_at = to_sqlite_ts(msg.get("date", ""))

            raw_json = json.dumps(
                {
                    "title": title,
                    "body": plain_body,
                    "takeaway": "",
                    "imported_from": "tg_export",
                    "tg_message_id": msg_id,
                },
                ensure_ascii=False,
            )

            if preview_shown < 3:
                logger.info(
                    "preview #{}: tg_id={} title={!r} url={} html_len={}",
                    preview_shown + 1,
                    msg_id,
                    title,
                    source_url,
                    len(formatted_html),
                )
                logger.info("  html: {}", formatted_html[:280])
                preview_shown += 1

            if dry_run:
                imported += 1
                continue

            try:
                cur = await conn.execute(
                    "INSERT INTO drafts "
                    "(created_at, raw_json, formatted_text, primary_source_url, status) "
                    "VALUES (?, ?, ?, ?, 'published')",
                    (created_at, raw_json, formatted_html, source_url),
                )
                draft_id = cur.lastrowid

                pub_cur = await conn.execute(
                    "INSERT OR IGNORE INTO published "
                    "(draft_id, source_url, title, published_at, tg_message_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (draft_id, source_url, title, created_at, msg_id),
                )
                if pub_cur.rowcount == 0:
                    # Коллизия по UNIQUE source_url с уже существующей записью.
                    # Удаляем только что вставленный draft, чтобы не плодить сирот.
                    await conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
                    skipped_existing += 1
                    await conn.commit()
                    continue

                await conn.commit()
                imported += 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                logger.exception("Failed to import msg_id={}: {}", msg_id, exc)
                try:
                    await conn.rollback()
                except Exception:  # noqa: BLE001
                    pass

    logger.info(
        "Done: imported={} skipped_existing={} skipped_empty={} errors={} dry_run={}",
        imported,
        skipped_existing,
        skipped_empty,
        errors,
        dry_run,
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Backfill channel archive from TG Desktop export")
    p.add_argument("--input", required=True, type=Path, help="Path to result.json")
    p.add_argument(
        "--channel-username",
        required=True,
        help="Channel @username without @ (used to build https://t.me/<u>/<id>)",
    )
    p.add_argument("--dry-run", action="store_true", help="Parse and report, no DB writes")
    p.add_argument("--limit", type=int, default=None, help="Stop after N processed messages")
    args = p.parse_args()

    if not args.input.exists():
        logger.error("Input file not found: {}", args.input)
        sys.exit(1)

    data = json.loads(args.input.read_text(encoding="utf-8"))
    messages = [m for m in data.get("messages", []) if m.get("type") == "message"]
    logger.info("Loaded {} messages from {}", len(messages), args.input)

    asyncio.run(
        import_messages(
            messages=messages,
            channel_username=args.channel_username.lstrip("@"),
            dry_run=args.dry_run,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
