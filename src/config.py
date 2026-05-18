from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    owner_id: int = Field(..., alias="OWNER_ID")
    channel_id: str = Field(..., alias="CHANNEL_ID")

    anthropic_api_key: str = Field(..., alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field("claude-sonnet-4-5", alias="ANTHROPIC_MODEL")

    db_path: Path = Field(Path("./data/smm.db"), alias="DB_PATH")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    web_search_max_uses: int = Field(5, alias="WEB_SEARCH_MAX_USES")
    web_search_country: str = Field("RU", alias="WEB_SEARCH_COUNTRY")


settings = Settings()  # type: ignore[call-arg]
