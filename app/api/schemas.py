from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class SettingsPatchRequest(BaseModel):
    updates: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    prompt: str
    model: str | None = None
    profile: str | None = None
    fallback_profiles: str | None = None
    image_urls: list[str] = Field(default_factory=list)


class SummaryRequest(BaseModel):
    text: str | None = None
    messages: list[str] = Field(default_factory=list)
    model: str | None = None
    profile: str | None = None
    fallback_profiles: str | None = None
    include_image_hints: bool = False

    @model_validator(mode="after")
    def validate_source(self):
        if not self.text and not self.messages:
            raise ValueError("text 和 messages 至少要提供一个。")
        return self


class DrawRequest(BaseModel):
    prompt: str = ""
    model: str | None = None
    profile: str | None = None
    fallback_profiles: str | None = None
    size: str = "1:1"
    variants: int = 1
    urls: list[str] = Field(default_factory=list)
    web_hook: str | None = None
    shut_progress: bool = False


class DrawResultRequest(BaseModel):
    id: str
    profile: str | None = None
    provider: str | None = None


class MinecraftChatEvent(BaseModel):
    server_id: str = Field(default="default", max_length=64)
    player_uuid: str = Field(max_length=64)
    player_name: str = Field(max_length=16)
    message: str = Field(max_length=500)
    world: str | None = Field(default=None, max_length=64)

    @field_validator("server_id", "player_uuid", "player_name", "message", "world", mode="before")
    @classmethod
    def trim_text(cls, value):
        if value is None:
            return None
        return str(value).strip()


class MinecraftQueuedMessage(BaseModel):
    id: int
    username: str
    display_name: str
    discord_user_id: str
    content: str
    created_at: str


class MinecraftMessagesResponse(BaseModel):
    messages: list[MinecraftQueuedMessage] = Field(default_factory=list)
    next_after: int = 0


class MinecraftBindingRequest(BaseModel):
    username: str = Field(max_length=16)

    @field_validator("username", mode="before")
    @classmethod
    def trim_username(cls, value):
        return str(value).strip()


class MinecraftPlayerEvent(BaseModel):
    server_id: str = Field(default="default", max_length=64)
    event_type: str = Field(max_length=16)  # "join" or "quit"
    player_name: str = Field(max_length=16)
    player_uuid: str = Field(max_length=64)

    @field_validator("server_id", "event_type", "player_name", "player_uuid", mode="before")
    @classmethod
    def trim_text(cls, value):
        if value is None:
            return None
        return str(value).strip()


class MinecraftTellRequest(BaseModel):
    target_player: str = Field(max_length=16)
    message: str = Field(max_length=500)

    @field_validator("target_player", "message", mode="before")
    @classmethod
    def trim_text(cls, value):
        return str(value).strip()


class MinecraftPendingTell(BaseModel):
    id: int
    from_user: str
    message: str
    created_at: str


class MinecraftPendingTellsResponse(BaseModel):
    player_name: str
    tells: list[MinecraftPendingTell] = Field(default_factory=list)


class MinecraftOnlinePlayersResponse(BaseModel):
    server_id: str
    online_count: int
    max_players: int
    players: list[str] = Field(default_factory=list)
