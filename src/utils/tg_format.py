from __future__ import annotations

import re
from html import escape

from src.agent.schemas import PostDraft

TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_MESSAGE_LIMIT = 4096

# Разрешённые теги Telegram, которые модель может использовать в body.
# Telegram сам валидирует — но мы тоже подстрахуемся.
_ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "s", "code", "pre", "a", "blockquote"}
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)(\s[^>]*)?>")


def _sanitize_body(html: str) -> str:
    """Удаляет неразрешённые теги, превращая их в экранированный текст.

    Минимальная защита: если модель внезапно вернёт <script> или <p>,
    тег не сломает отправку в Telegram.
    """

    def repl(m: re.Match[str]) -> str:
        tag = m.group(2).lower()
        if tag in _ALLOWED_TAGS:
            return m.group(0)
        return escape(m.group(0))

    return _TAG_RE.sub(repl, html)


def format_post(draft: PostDraft) -> str:
    """Готовый HTML-текст поста для Telegram."""
    title = escape(draft.title.strip())
    body = _sanitize_body(draft.body.strip())
    why = escape(draft.why_it_matters.strip())
    source = escape(str(draft.primary_source_url))

    parts = [
        f"<b>{title}</b>",
        "",
        body,
        "",
        why,
        "",
        f'<a href="{source}">Источник</a>',
    ]

    return "\n".join(parts)


def fits_caption(text: str) -> bool:
    return len(text) <= TELEGRAM_CAPTION_LIMIT


def truncate_to_message(text: str) -> str:
    if len(text) <= TELEGRAM_MESSAGE_LIMIT:
        return text
    cutoff = TELEGRAM_MESSAGE_LIMIT - 1
    snippet = text[:cutoff]
    last_space = snippet.rfind(" ")
    if last_space > cutoff - 200:
        snippet = snippet[:last_space]
    return snippet + "…"
