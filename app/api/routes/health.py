from __future__ import annotations

import os

from fastapi import APIRouter, Request


router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def health(request: Request) -> dict[str, object]:
    env = request.app.state.env
    bot_manager = request.app.state.bot_manager
    global_settings = await request.app.state.store.get_global_settings()
    return {
        "status": "ok",
        "bot_running": bot_manager.is_running(),
        "bot_last_error": bot_manager.last_error,
        "discord_token_configured": bool(env.discord_token),
        "openrouter_configured": bool(env.openrouter_api_key),
        "grsai_configured": bool(os.getenv("GRSAI_API_KEY") or env.openrouter_api_key),
        "danbooru_configured": bool(env.danbooru_username and env.danbooru_api_key),
        "rule34_configured": bool(env.rule34_api_base_url and env.rule34_post_base_url and env.rule34_user_id and env.rule34_api_key),
        "saucenao_configured": bool(env.saucenao_api_key),
        "provider_file": str(env.ai_provider_file),
        "persona_file": str(env.persona_file),
        "chat_model_profile": global_settings.chat_model_profile,
        "chat_fallback_profiles": global_settings.chat_fallback_profiles,
        "draw_model_profile": global_settings.draw_model_profile,
        "draw_fallback_profiles": global_settings.draw_fallback_profiles,
        "persona_profile": getattr(global_settings, "persona_profile", "glados"),
        "providers": request.app.state.openrouter.list_providers(),
        "image_profiles": request.app.state.image_sources.list_profiles(),
        "personas": request.app.state.personas.list_profiles(),
    }
