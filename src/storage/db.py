from __future__ import annotations

import aiosqlite
from loguru import logger

from src.config import settings

# Таймаут на захват write-lock в SQLite. При WAL читатели не блокируют писателя,
# но два писателя всё равно сериализуются — даём 10s на отстой перед SQLITE_BUSY.
_BUSY_TIMEOUT_SEC = 10.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_json TEXT NOT NULL,
    formatted_text TEXT NOT NULL,
    image_url TEXT,
    image_file_id TEXT,
    primary_source_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
);

CREATE TABLE IF NOT EXISTS published (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id INTEGER REFERENCES drafts(id),
    source_url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    tg_message_id INTEGER
);

CREATE INDEX IF NOT EXISTS idx_published_at ON published(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_api_usage_ts ON api_usage(ts);

CREATE TABLE IF NOT EXISTS draft_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id INTEGER NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    actor_user_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_draft_events_draft ON draft_events(draft_id, created_at);
CREATE INDEX IF NOT EXISTS idx_draft_events_type_at ON draft_events(event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS post_reactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_message_id INTEGER NOT NULL,
    channel_id TEXT NOT NULL,
    total_count INTEGER NOT NULL DEFAULT 0,
    reactions_json TEXT NOT NULL DEFAULT '[]',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tg_message_id, channel_id)
);
CREATE INDEX IF NOT EXISTS idx_post_reactions_total ON post_reactions(total_count DESC);

CREATE TABLE IF NOT EXISTS channel_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    channel_id TEXT NOT NULL,
    member_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_channel_snapshots_ts ON channel_snapshots(channel_id, ts DESC);
"""


async def _ensure_column(
    conn: aiosqlite.Connection, table: str, column: str, col_def: str
) -> None:
    async with conn.execute(f"PRAGMA table_info({table})") as cur:
        cols = [row[1] async for row in cur]
    if column not in cols:
        await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
        logger.info("Migrated: added {}.{}", table, column)


async def init_db() -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(settings.db_path, timeout=_BUSY_TIMEOUT_SEC) as conn:
        # WAL — это per-database setting (хранится в заголовке файла), достаточно
        # выставить один раз. synchronous=NORMAL даёт безопасный fsync на checkpoint
        # вместо каждой транзакции. Под нашей нагрузкой (десятки коммитов в день)
        # этого с запасом.
        async with conn.execute("PRAGMA journal_mode=WAL") as cur:
            mode_row = await cur.fetchone()
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.executescript(SCHEMA)
        await _ensure_column(conn, "drafts", "image_file_id", "TEXT")
        await conn.commit()
    logger.info(
        "SQLite ready at {} (journal_mode={})",
        settings.db_path,
        mode_row[0] if mode_row else "unknown",
    )


def get_conn() -> aiosqlite.Connection:
    """Возвращает coroutine-объект (aiosqlite.connect) — используется через `async with`.

    `timeout` пробрасывается в sqlite3.connect и задаёт busy_timeout: сколько
    SQLite ждёт write-lock до SQLITE_BUSY. В сочетании с WAL это устраняет
    типичные конфликты между cron-job и FastAPI-читателями.
    """
    return aiosqlite.connect(settings.db_path, timeout=_BUSY_TIMEOUT_SEC)
