from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class PostDraft(BaseModel):
    """Структурированный результат работы агента.

    Лимиты подобраны так, чтобы итоговый formatted_text влезал в Telegram
    caption (1024 символа) и поэтому мог быть отправлен одним сообщением
    photo+caption.
    """

    # min_length — нижний предел валидности (защита от обрезков), а не
    # стилевой таргет. Целевые длины (title 40–90, body 300–550,
    # takeaway 80–220) задаёт SYSTEM_PROMPT. При провале валидации длины
    # агент просит модель переотправить submit_post (см. news_agent цикл).
    title: str = Field(..., min_length=25, max_length=110)
    body: str = Field(..., min_length=200, max_length=680)
    takeaway: str = Field(..., min_length=60, max_length=260)
    primary_source_url: HttpUrl
    extra_sources: list[HttpUrl] = Field(default_factory=list)


class NoNews(BaseModel):
    no_news: bool = True
    reason: str | None = None


AgentResult = PostDraft | NoNews
