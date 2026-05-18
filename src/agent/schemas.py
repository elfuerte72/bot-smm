from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class PostDraft(BaseModel):
    """Структурированный результат работы агента."""

    title: str = Field(..., min_length=5, max_length=200)
    body: str = Field(..., min_length=200, max_length=4000)
    why_it_matters: str = Field(..., min_length=20, max_length=600)
    primary_source_url: HttpUrl
    extra_sources: list[HttpUrl] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class NoNews(BaseModel):
    no_news: bool = True
    reason: str | None = None


AgentResult = PostDraft | NoNews
