from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class PostDraft(BaseModel):
    """Структурированный результат работы агента.

    Лимиты подобраны так, чтобы итоговый formatted_text влезал в Telegram
    caption (1024 символа) и поэтому мог быть отправлен одним сообщением
    photo+caption.
    """

    title: str = Field(..., min_length=10, max_length=120)
    body: str = Field(..., min_length=200, max_length=750)
    why_it_matters: str = Field(..., min_length=20, max_length=220)
    primary_source_url: HttpUrl
    extra_sources: list[HttpUrl] = Field(default_factory=list)


class NoNews(BaseModel):
    no_news: bool = True
    reason: str | None = None


AgentResult = PostDraft | NoNews
