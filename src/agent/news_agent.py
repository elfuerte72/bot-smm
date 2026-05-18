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


async def generate_post(*, exclude_urls: list[str] | None = None) -> AgentResult:
    """Один прогон агента: вызов Claude с web_search, парс JSON, валидация."""
    exclude_urls = exclude_urls or []
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    user_prompt = build_user_prompt(exclude_urls=exclude_urls)

    logger.info(
        "Calling Claude (model={}, excluded={} urls)",
        settings.anthropic_model,
        len(exclude_urls),
    )

    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
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

    text = _final_text(response.content)
    if not text:
        raise AgentError("Модель не вернула финальный текст — нет text-блоков в ответе")

    payload = _extract_json(text)
    if payload is None:
        logger.error("Ответ модели не содержит JSON. Текст: {}", text[:500])
        raise AgentError("Не нашёл JSON в ответе модели")

    if payload.get("no_news"):
        return NoNews.model_validate(payload)

    try:
        return PostDraft.model_validate(payload)
    except ValidationError as e:
        logger.error("PostDraft validation failed: {}\nPayload: {}", e, payload)
        raise AgentError(f"PostDraft не прошёл валидацию: {e}") from e


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
