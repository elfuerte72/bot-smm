from __future__ import annotations

import re
from html import escape, unescape

from src.agent.schemas import PostDraft

TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_MESSAGE_LIMIT = 4096

# Удаляет любой HTML-тег целиком (включая <a href="...">: href внутри <...>
# тоже срезается, остаётся только якорный текст). URL не содержат сырого '>'.
_STRIP_TAGS_RE = re.compile(r"<[^>]+>")

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
    why = escape(draft.takeaway.strip())
    source = escape(str(draft.primary_source_url))

    parts = [
        f"<b>{title}</b>",
        "",
        body,
        "",
        f"<blockquote>{why}</blockquote>",
        "",
        f'<a href="{source}">Источник</a>',
    ]

    return "\n".join(parts)


def visible_len(text: str) -> int:
    """Длина текста так, как её считает Telegram: после парсинга entities.

    Лимит caption (1024) Telegram применяет к ВИДИМОМУ тексту, а не к сырому
    HTML. Поэтому теги (<b>, <blockquote>, ...) и особенно href внутри
    <a href="URL"> в счёт не идут, видимыми остаются только символы и якорный
    текст ссылки. Сырой len(text) переоценивал длину и гнал посты в разбивку
    на два сообщения без необходимости.
    """
    return len(unescape(_STRIP_TAGS_RE.sub("", text)))


def fits_caption(text: str) -> bool:
    return visible_len(text) <= TELEGRAM_CAPTION_LIMIT


def truncate_to_message(text: str) -> str:
    if len(text) <= TELEGRAM_MESSAGE_LIMIT:
        return text
    cutoff = TELEGRAM_MESSAGE_LIMIT - 1
    snippet = text[:cutoff]
    last_space = snippet.rfind(" ")
    if last_space > cutoff - 200:
        snippet = snippet[:last_space]
    return snippet + "…"
