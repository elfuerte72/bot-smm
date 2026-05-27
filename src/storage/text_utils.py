from __future__ import annotations

import html
import re

# HTML-разметка наша (см. SYSTEM_PROMPT в src/agent/prompts.py): только
# <b>, <i>, <u>, <s>, <code>, <pre>, <a>, <blockquote>, <tg-spoiler>, <br>.
# Полноценный парсер не нужен, регулярки безопасны для этого подмножества.

_BR_RE = re.compile(r"(?i)<br\s*/?>")
_BLOCK_END_RE = re.compile(r"(?is)</(p|div|blockquote|pre)>")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def html_to_plain(s: str) -> str:
    s = _BR_RE.sub(" ", s)
    s = _BLOCK_END_RE.sub(" ", s)
    s = _TAG_RE.sub("", s)
    s = html.unescape(s)
    return _WS_RE.sub(" ", s).strip()


def make_preview(s: str, *, max_chars: int = 200) -> str:
    plain = html_to_plain(s)
    if len(plain) <= max_chars:
        return plain
    cut = plain.rfind(" ", 0, max_chars)
    if cut < int(max_chars * 0.6):
        cut = max_chars
    return plain[:cut].rstrip() + "…"
