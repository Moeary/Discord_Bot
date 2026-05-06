from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GlobalSettings(BaseModel):
    openrouter_model: str = "openrouter/auto"
    draw_model: str = "sora-image"
    chat_provider: str = "legacy"
    chat_fallback_providers: str = ""
    draw_provider: str = "legacy"
    draw_fallback_providers: str = ""
    chat_model_profile: str = "legacy-chat"
    chat_fallback_profiles: str = ""
    draw_model_profile: str = "legacy-draw"
    draw_fallback_profiles: str = ""
    persona_profile: str = "glados"
    max_chat_history: int = 12


class GuildSettings(BaseModel):
    guild_name: str = ""
    ai_enabled: bool = True
    fun_enabled: bool = True
    tax_enabled: bool = True
    minecraft_bridge_enabled: bool = False
    minecraft_server_id: str = "default"
    minecraft_server_address: str = ""
    minecraft_channel_id: int | None = None
    minecraft_token: str = ""
    minecraft_allow_no_token: bool = True
    minecraft_max_message_length: int = 300
    welcome_channel_id: int | None = None
    welcome_text: str = "{user_mention} 欢迎来到 {guild_name}。请别立刻把这里炸了。"
    verification_channel_id: int | None = None
    verification_role_id: int | None = None
    verification_question: str = "Minecraft的中文译名是什么"
    verification_answer: str = "我的世界"
    verification_success_text: str = "{user_mention} 验证通过，已领取身份组 {role_mention}。"
    tax_channel_id: int | None = None
    log_channel_id: int | None = None
    shit_emoji: str = "shit,💩,poop,pile_of_poo"
    tax_required_images: int = 3
    tax_payment_window_minutes: int = 15
    mute_hours: int = 1
    summary_limit: int = 40
    danbooru_default_tags: str = "rating:safe"
    safe_image_site_profile: str = "danbooru"
    explicit_image_site_profile: str = "danbooru"
    safe_image_default_tags: str = ""
    explicit_image_default_tags: str = ""
    warn_text: str = (
        "{user_mention} 你的图片被鉴定为屎，请在 {tax_channel} "
        "{minutes} 分钟内补税 {required_images} 张图，否则禁言 {mute_hours} 小时。"
    )


class UserStats(BaseModel):
    warnings: int = 0
    taxes_paid: int = 0
    taxes_failed: int = 0
    ai_calls: int = 0
    danbooru_calls: int = 0
    fortune_calls: int = 0


class UserImagePreferences(BaseModel):
    safe_image_site_profile: str = ""
    explicit_image_site_profile: str = ""
    safe_image_tags: str = ""
    explicit_image_tags: str = ""


class GuildStats(BaseModel):
    total_tax_cases: int = 0
    user_stats: dict[str, UserStats] = Field(default_factory=dict)


class TaxCase(BaseModel):
    case_id: str
    guild_id: int
    user_id: int
    trigger_channel_id: int
    message_id: int
    triggered_by_user_id: int
    required_images: int
    submitted_images: int = 0
    status: Literal["pending", "paid", "expired"] = "pending"
    created_at: datetime = Field(default_factory=utcnow)
    deadline_at: datetime
    completed_at: datetime | None = None


class AppState(BaseModel):
    global_settings: GlobalSettings = Field(default_factory=GlobalSettings)
    guilds: dict[str, GuildSettings] = Field(default_factory=dict)
    stats: dict[str, GuildStats] = Field(default_factory=dict)
    user_preferences: dict[str, dict[str, UserImagePreferences]] = Field(default_factory=dict)
    minecraft_bindings: dict[str, dict[str, str]] = Field(default_factory=dict)
    tax_cases: list[TaxCase] = Field(default_factory=list)
