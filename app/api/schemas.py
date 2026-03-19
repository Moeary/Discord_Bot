from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class SettingsPatchRequest(BaseModel):
    updates: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    prompt: str
    system_prompt: str | None = None
    model: str | None = None
    provider: str | None = None
    fallback_providers: str | None = None
    image_urls: list[str] = Field(default_factory=list)


class SummaryRequest(BaseModel):
    text: str | None = None
    messages: list[str] = Field(default_factory=list)
    model: str | None = None
    provider: str | None = None
    fallback_providers: str | None = None
    include_image_hints: bool = False

    @model_validator(mode="after")
    def validate_source(self):
        if not self.text and not self.messages:
            raise ValueError("text 和 messages 至少要提供一个。")
        return self


class DrawRequest(BaseModel):
    prompt: str
    model: str = "sora-image"
    provider: str | None = None
    fallback_providers: str | None = None
    size: str = "1:1"
    variants: int = 1
    urls: list[str] = Field(default_factory=list)
    web_hook: str | None = None
    shut_progress: bool = False


class DrawResultRequest(BaseModel):
    id: str
    provider: str | None = None
