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
"""


async def init_db() -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(settings.db_path) as conn:
        await conn.executescript(SCHEMA)
        await conn.commit()
    logger.info("SQLite ready at {}", settings.db_path)


def get_conn() -> aiosqlite.Connection:
    """Возвращает coroutine-объект (aiosqlite.connect) — используется через `async with`."""
    return aiosqlite.connect(settings.db_path)
