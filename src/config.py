from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    owner_id: int = Field(..., alias="OWNER_ID")
    extra_user_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=list, alias="EXTRA_USER_IDS"
    )
    channel_id: str = Field(..., alias="CHANNEL_ID")

    @field_validator("extra_user_ids", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [int(x) for x in v.split(",") if x.strip()]
        return v

    @property
    def allowed_user_ids(self) -> set[int]:
        return {self.owner_id, *self.extra_user_ids}

    anthropic_api_key: str = Field(..., alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field("claude-sonnet-4-5", alias="ANTHROPIC_MODEL")

    db_path: Path = Field(Path("./data/smm.db"), alias="DB_PATH")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    web_search_max_uses: int = Field(5, alias="WEB_SEARCH_MAX_USES")
    web_search_country: str = Field("RU", alias="WEB_SEARCH_COUNTRY")


settings = Settings()  # type: ignore[call-arg]
