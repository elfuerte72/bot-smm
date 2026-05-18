from __future__ import annotations

from html import escape

from src.agent.schemas import PostDraft

TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_MESSAGE_LIMIT = 4096


def format_post(draft: PostDraft) -> str:
    """Готовый HTML-текст поста для Telegram. Без эмодзи."""
    title = escape(draft.title.strip())
    body = escape(draft.body.strip())
    why = escape(draft.why_it_matters.strip())
    source = str(draft.primary_source_url)

    parts = [
        f"<b>{title}</b>",
        "",
        body,
        "",
        why,
        "",
        f'<a href="{escape(source)}">Источник</a>',
    ]

    if draft.tags:
        cleaned = " ".join(escape(t if t.startswith("#") else f"#{t}") for t in draft.tags)
        parts.append("")
        parts.append(cleaned)

    return "\n".join(parts)


def fits_caption(text: str) -> bool:
    return len(text) <= TELEGRAM_CAPTION_LIMIT


def truncate_to_message(text: str) -> str:
    if len(text) <= TELEGRAM_MESSAGE_LIMIT:
        return text
    # обрезаем по слову, оставляем место под "…"
    cutoff = TELEGRAM_MESSAGE_LIMIT - 1
    snippet = text[:cutoff]
    last_space = snippet.rfind(" ")
    if last_space > cutoff - 200:
        snippet = snippet[:last_space]
    return snippet + "…"
