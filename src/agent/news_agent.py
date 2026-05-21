from __future__ import annotations

import asyncio
import json
import re

from anthropic import AsyncAnthropic
from loguru import logger
from pydantic import ValidationError

from src.agent.prompts import SYSTEM_PROMPT, build_user_prompt
from src.agent.schemas import AgentResult, NoNews, PostDraft
from src.config import settings


class AgentError(RuntimeError):
    """Что-то пошло не так в работе агента (нет JSON, нет ответа и т.п.)."""


_JSON_BLOCK_RE = re.compile(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}", re.DOTALL)

# em-dash и en-dash вокруг (возможных) пробелов
_DASH_RE = re.compile(r"\s*[—–]\s*")


_DOUBLE_COMMA_RE = re.compile(r",\s*,(\s*,)*")
_COMMA_BEFORE_PUNCT_RE = re.compile(r",\s+([.,!?;:)])")
_LEADING_COMMA_RE = re.compile(r"(^|\n)\s*,\s*")


def _strip_dashes(text: str) -> str:
    """Убирает «—» и «–» из текста, заменяя на «, ».

    Модель регулярно срывается на тире, даже когда явно запрещено. Делаем
    детерминированный фолбэк на стороне Python и подчищаем артефакты замены
    (двойные запятые, запятые перед знаками препинания и в начале строки).
    """
    text = _DASH_RE.sub(", ", text)
    text = _DOUBLE_COMMA_RE.sub(",", text)
    text = _COMMA_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = _LEADING_COMMA_RE.sub(r"\1", text)
    return text


def _scrub_payload(payload: dict) -> dict:
    """Прогоняет текстовые поля черновика через _strip_dashes."""
    for key in ("title", "body", "why_it_matters"):
        if isinstance(payload.get(key), str):
            payload[key] = _strip_dashes(payload[key])
    return payload


def _extract_json(text: str) -> dict | None:
    """Достаёт первый валидный JSON-объект из текста.

    Модель просили вернуть голый JSON, но иногда обёрнет в ```json … ```.
    """
    text = text.strip()
    # уберём ```json ... ``` если есть
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    for match in _JSON_BLOCK_RE.finditer(text):
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _final_text(response_content: list) -> str:
    """Собирает все text-блоки из ответа модели (после server tool calls)."""
    parts: list[str] = []
    for block in response_content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


async def _shrink_draft(
    client: AsyncAnthropic, payload: dict, errors: list[str]
) -> dict | None:
    """Просит модель ужать поля черновика до лимитов и возвращает новый JSON.

    Вызов идёт без web_search: модели нужно только переписать существующий
    черновик, новые факты искать не надо. Это и быстрее, и не тратит лимиты.
    """
    fix_prompt = (
        "Черновик поста не прошёл валидацию pydantic. Ошибки:\n"
        + "\n".join(f"- {e}" for e in errors)
        + "\n\nТекущий JSON:\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n\nИсправь длины полей:\n"
        "- body: 400–650 символов (жёсткий потолок 700), считая HTML-теги;\n"
        "- title: 40–80 символов;\n"
        "- why_it_matters: 80–180 символов.\n"
        "Сохрани смысл, HTML-разметку, primary_source_url и extra_sources.\n"
        "Не добавляй новые факты, не используй «—» и «–».\n"
        "Верни ТОЛЬКО исправленный JSON без markdown-обёртки."
    )

    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": fix_prompt}],
    )
    text = _final_text(response.content)
    return _extract_json(text)


async def generate_post(
    *,
    exclude_urls: list[str] | None = None,
    exclude_topics: list[str] | None = None,
) -> AgentResult:
    """Один прогон агента: вызов Claude с web_search, парс JSON, валидация."""
    exclude_urls = exclude_urls or []
    exclude_topics = exclude_topics or []
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    user_prompt = build_user_prompt(
        exclude_urls=exclude_urls,
        exclude_topics=exclude_topics,
    )

    logger.info(
        "Calling Claude (model={}, excluded urls={}, excluded topics={})",
        settings.anthropic_model,
        len(exclude_urls),
        len(exclude_topics),
    )

    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        # cache_control на последнем блоке system делает breakpoint:
        # tools + system кешируются на 5 минут. Повторный /generate в окне
        # читает их по цене ~10% от input. Cache write на первой записи
        # стоит +25% к обычной цене input — окупается со 2-го вызова.
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": settings.web_search_max_uses,
                "user_location": {
                    "type": "approximate",
                    "country": settings.web_search_country,
                },
            }
        ],
        messages=[{"role": "user", "content": user_prompt}],
    )

    usage = response.usage
    logger.info(
        "Tokens: in={} out={} cache_create={} cache_read={}",
        getattr(usage, "input_tokens", "?"),
        getattr(usage, "output_tokens", "?"),
        getattr(usage, "cache_creation_input_tokens", 0),
        getattr(usage, "cache_read_input_tokens", 0),
    )

    text = _final_text(response.content)
    if not text:
        raise AgentError("Модель не вернула финальный текст — нет text-блоков в ответе")

    payload = _extract_json(text)
    if payload is None:
        logger.error("Ответ модели не содержит JSON. Текст: {}", text[:500])
        raise AgentError("Не нашёл JSON в ответе модели")

    if payload.get("no_news"):
        return NoNews.model_validate(payload)

    payload = _scrub_payload(payload)

    try:
        return PostDraft.model_validate(payload)
    except ValidationError as e:
        errors = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
        logger.warning("PostDraft validation failed, retrying shrink: {}", errors)

        fixed = await _shrink_draft(client, payload, errors)
        if fixed is None:
            logger.error("Shrink retry: модель не вернула JSON")
            raise AgentError("Не нашёл JSON в ответе модели на ретрае") from e

        fixed = _scrub_payload(fixed)
        try:
            return PostDraft.model_validate(fixed)
        except ValidationError as e2:
            logger.error(
                "PostDraft validation failed after shrink retry: {}\nPayload: {}",
                e2,
                fixed,
            )
            raise AgentError(f"PostDraft не прошёл валидацию после ретрая: {e2}") from e2


async def _cli() -> None:
    import sys

    from loguru import logger as _logger

    _logger.remove()
    _logger.add(sys.stderr, level="INFO")

    result = await generate_post()
    if isinstance(result, NoNews):
        print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
        return

    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_cli())
