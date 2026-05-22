from __future__ import annotations

import asyncio
import json
import re

from anthropic import AsyncAnthropic
from loguru import logger
from pydantic import ValidationError

from src.agent.pricing import estimate_cost_usd
from src.agent.prompts import SYSTEM_PROMPT, build_user_prompt
from src.agent.schemas import AgentResult, NoNews, PostDraft
from src.config import settings
from src.storage import repo


class AgentError(RuntimeError):
    """Что-то пошло не так в работе агента (нет ответа, лимит итераций и т.п.)."""


# Сколько раз готовы прокрутить tool-use цикл: server tools (web_search,
# web_fetch) API отрабатывает внутри одного ответа, итерации тратятся на
# client tools (check_topic_covered, повторный submit_post после ошибки
# валидации). 6 хватает на проверку темы + пару ретраев длины.
_MAX_ITERATIONS = 6

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
    for key in ("title", "body", "takeaway"):
        if isinstance(payload.get(key), str):
            payload[key] = _strip_dashes(payload[key])
    return payload


# Server tool: поиск свежих инфоповодов и проверка фактов.
_WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": settings.web_search_max_uses,
    "user_location": {
        "type": "approximate",
        "country": settings.web_search_country,
    },
}

# Server tool: чтение конкретной страницы по URL (режим source_url).
_WEB_FETCH_TOOL = {
    "type": "web_fetch_20250910",
    "name": "web_fetch",
    "max_uses": settings.web_fetch_max_uses,
}

# Client tool: единственный способ вернуть готовый пост. strict гарантирует
# структуру JSON; длины полей всё равно проверяет PostDraft (см. цикл ниже).
_SUBMIT_POST_TOOL = {
    "name": "submit_post",
    "description": "Вернуть готовый пост для канала. Единственный способ отдать результат.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {
                "type": "string",
                "description": "Заголовок-хук, plain text без HTML, без точки в конце. "
                "Целевая длина 40-90 символов.",
            },
            "body": {
                "type": "string",
                "description": "HTML-форматированный текст для Telegram, только "
                "разрешённые теги. Целевая длина 300-550 символов, жёсткий потолок 650.",
            },
            "takeaway": {
                "type": "string",
                "description": "Экспертный вывод без ярлыка. Целевая длина 80-220 символов.",
            },
            "primary_source_url": {
                "type": "string",
                "description": "URL самого авторитетного источника новости.",
            },
            "extra_sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Дополнительные URL-источники. Пустой массив, если их нет.",
            },
        },
        "required": ["title", "body", "takeaway", "primary_source_url", "extra_sources"],
    },
}

# Client tool: способ сообщить, что подходящей новости нет.
_REPORT_NO_NEWS_TOOL = {
    "name": "report_no_news",
    "description": "Сообщить, что подходящей свежей новости нет.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "reason": {
                "type": "string",
                "description": "Краткое объяснение, почему пост не сделан.",
            },
        },
        "required": ["reason"],
    },
}

# Client tool: жёсткая проверка дублей тем через SQLite.
_CHECK_TOPIC_TOOL = {
    "name": "check_topic_covered",
    "description": "Проверить, не публиковал ли канал уже пост про это событие. "
    "Вызови перед submit_post с заголовком или сутью найденной новости.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "headline": {
                "type": "string",
                "description": "Заголовок или краткая суть найденной новости.",
            },
        },
        "required": ["headline"],
    },
}

_TOOLS = [
    _WEB_SEARCH_TOOL,
    _WEB_FETCH_TOOL,
    _SUBMIT_POST_TOOL,
    _REPORT_NO_NEWS_TOOL,
    _CHECK_TOPIC_TOOL,
]

# cache_control на последнем блоке system делает breakpoint: tools + system
# кешируются на 5 минут. Повторный /generate в окне читает их по цене ~10%
# от input. Cache write на первой записи стоит +25% — окупается со 2-го вызова.
_SYSTEM_BLOCKS = [
    {
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }
]


async def _log_and_record_usage(model: str, usage) -> None:
    """Пишет токены в loguru и фиксирует расход в локальном счётчике."""
    in_t = int(getattr(usage, "input_tokens", 0) or 0)
    out_t = int(getattr(usage, "output_tokens", 0) or 0)
    cc_t = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    cr_t = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cost = estimate_cost_usd(
        model,
        input_tokens=in_t,
        output_tokens=out_t,
        cache_creation_tokens=cc_t,
        cache_read_tokens=cr_t,
    )
    logger.info(
        "Tokens: in={} out={} cache_create={} cache_read={} cost=${:.6f}",
        in_t,
        out_t,
        cc_t,
        cr_t,
        cost,
    )
    try:
        await repo.record_api_usage(
            model=model,
            input_tokens=in_t,
            output_tokens=out_t,
            cache_creation_tokens=cc_t,
            cache_read_tokens=cr_t,
            cost_usd=cost,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Не смог записать api_usage в БД: {}", e)


async def _handle_check_topic(headline: str) -> str:
    """Содержимое tool_result для check_topic_covered: список похожих тем."""
    matches = await repo.find_similar_topics(headline)
    if not matches:
        return "Совпадений не найдено: тема свободна, можно писать пост."
    listed = "\n".join(f"- {m}" for m in matches)
    return (
        "Тема уже освещена. Похожие заголовки недавних постов:\n"
        + listed
        + "\nНайди другой инфоповод и проверь его снова."
    )


async def generate_post(
    *,
    exclude_urls: list[str] | None = None,
    exclude_topics: list[str] | None = None,
    topic: str | None = None,
    source_url: str | None = None,
) -> AgentResult:
    """Один прогон агента: tool-use цикл с Claude.

    Модель сама ходит в web_search/web_fetch (server tools), проверяет дубли
    через check_topic_covered и возвращает результат строго через client tool
    submit_post или report_no_news. Парсить текст не нужно — берём tool input.
    """
    exclude_urls = exclude_urls or []
    exclude_topics = exclude_topics or []
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    model = settings.anthropic_model

    user_prompt = build_user_prompt(
        exclude_urls=exclude_urls,
        exclude_topics=exclude_topics,
        topic=topic,
        source_url=source_url,
    )

    logger.info(
        "Calling Claude (model={}, excluded urls={}, excluded topics={}, "
        "topic={!r}, source_url={!r})",
        model,
        len(exclude_urls),
        len(exclude_topics),
        topic,
        source_url,
    )

    messages: list[dict] = [{"role": "user", "content": user_prompt}]
    nudged = False

    for _ in range(_MAX_ITERATIONS):
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=_SYSTEM_BLOCKS,
            tools=_TOOLS,
            messages=messages,
        )
        await _log_and_record_usage(model, response.usage)
        messages.append({"role": "assistant", "content": response.content})

        # type == "tool_use" — только client tools; server tools (web_search,
        # web_fetch) приходят как server_tool_use и обрабатываются API сами.
        client_calls = [b for b in response.content if getattr(b, "type", None) == "tool_use"]

        if not client_calls:
            # pause_turn: server tool ещё работает — продолжаем без новых сообщений.
            if response.stop_reason == "pause_turn":
                continue
            if not nudged:
                nudged = True
                messages.append(
                    {
                        "role": "user",
                        "content": "Заверши работу: вызови submit_post с готовым "
                        "постом или report_no_news, если подходящей новости нет.",
                    }
                )
                continue
            raise AgentError("Модель не вызвала submit_post или report_no_news")

        tool_results: list[dict] = []
        for call in client_calls:
            if call.name == "report_no_news":
                return NoNews(reason=call.input.get("reason"))

            if call.name == "check_topic_covered":
                content = await _handle_check_topic(call.input.get("headline", ""))
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": call.id, "content": content}
                )
                continue

            if call.name == "submit_post":
                payload = _scrub_payload(dict(call.input))
                try:
                    return PostDraft.model_validate(payload)
                except ValidationError as e:
                    errors = [
                        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                        for err in e.errors()
                    ]
                    logger.warning("submit_post не прошёл валидацию: {}", errors)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": call.id,
                            "is_error": True,
                            "content": "Пост не прошёл валидацию:\n"
                            + "\n".join(f"- {e}" for e in errors)
                            + "\nИсправь длины полей (title 40-90, body 300-550 "
                            "потолок 650, takeaway 80-220) и вызови submit_post снова.",
                        }
                    )
                continue

            logger.warning("Неизвестный инструмент от модели: {}", call.name)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "is_error": True,
                    "content": "Неизвестный инструмент.",
                }
            )

        messages.append({"role": "user", "content": tool_results})

    raise AgentError("Превышен лимит итераций агента без результата")


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
