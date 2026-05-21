from __future__ import annotations

import aiosqlite
from loguru import logger

from src.config import settings

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
    async with aiosqlite.connect(settings.db_path) as conn:
        await conn.executescript(SCHEMA)
        await _ensure_column(conn, "drafts", "image_file_id", "TEXT")
        await conn.commit()
    logger.info("SQLite ready at {}", settings.db_path)


def get_conn() -> aiosqlite.Connection:
    """Возвращает coroutine-объект (aiosqlite.connect) — используется через `async with`."""
    return aiosqlite.connect(settings.db_path)
