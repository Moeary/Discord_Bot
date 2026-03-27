from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class EnvSettings(BaseSettings):
    discord_token: str | None = Field(default=None, alias="DISCORD_TOKEN")
    discord_test_guild_id: int | None = Field(default=None, alias="DISCORD_TEST_GUILD_ID")

    ai_provider_file: Path = Field(default=BASE_DIR / "data" / "providers.json", alias="AI_PROVIDER_FILE")
    persona_file: Path = Field(default=BASE_DIR / "data" / "personas.json", alias="PERSONA_FILE")
    ai_chat_provider: str = Field(default="legacy", alias="AI_CHAT_PROVIDER")
    ai_chat_fallbacks: str = Field(default="", alias="AI_CHAT_FALLBACKS")
    ai_draw_provider: str = Field(default="legacy", alias="AI_DRAW_PROVIDER")
    ai_draw_fallbacks: str = Field(default="", alias="AI_DRAW_FALLBACKS")

    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://grsaiapi.com/v1",
        alias="OPENROUTER_BASE_URL",
    )
    openrouter_model: str = Field(default="", alias="OPENROUTER_MODEL")
    draw_api_key: str | None = Field(default=None, alias="DRAW_API_KEY")
    draw_base_url: str = Field(
        default="https://grsaiapi.com/v1",
        alias="DRAW_BASE_URL",
    )
    draw_model: str = Field(default="", alias="DRAW_MODEL")
    openrouter_site_url: str | None = Field(default=None, alias="OPENROUTER_SITE_URL")
    openrouter_site_name: str | None = Field(default=None, alias="OPENROUTER_SITE_NAME")

    danbooru_base_url: str = Field(
        default="https://danbooru.donmai.us",
        alias="DANBOORU_BASE_URL",
    )
    danbooru_username: str | None = Field(default=None, alias="DANBOORU_USERNAME")
    danbooru_api_key: str | None = Field(default=None, alias="DANBOORU_API_KEY")
    rule34_api_base_url: str = Field(
        default="https://api.rule34.xxx",
        alias="RULE34_API_BASE_URL",
    )
    rule34_post_base_url: str = Field(
        default="https://rule34.xxx",
        alias="RULE34_POST_BASE_URL",
    )
    rule34_user_id: str | None = Field(default=None, alias="RULE34_USER_ID")
    rule34_api_key: str | None = Field(default=None, alias="RULE34_API_KEY")
    saucenao_base_url: str = Field(
        default="https://saucenao.com/search.php",
        alias="SAUCENAO_BASE_URL",
    )
    saucenao_api_key: str | None = Field(default=None, alias="SAUCENAO_API_KEY")

    state_file: Path = Field(default=BASE_DIR / "data" / "state.json", alias="STATE_FILE")
    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8000, alias="PORT")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("discord_test_guild_id", mode="before")
    @classmethod
    def empty_string_to_none(cls, value):
        if value in {"", None}:
            return None
        return value


@lru_cache(maxsize=1)
def get_env_settings() -> EnvSettings:
    settings = EnvSettings()
    if not settings.state_file.is_absolute():
        settings.state_file = BASE_DIR / settings.state_file
    if not settings.ai_provider_file.is_absolute():
        settings.ai_provider_file = BASE_DIR / settings.ai_provider_file
    if not settings.persona_file.is_absolute():
        settings.persona_file = BASE_DIR / settings.persona_file
    return settings
