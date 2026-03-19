from __future__ import annotations

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
        "danbooru_configured": bool(env.danbooru_username and env.danbooru_api_key),
        "chat_provider": global_settings.chat_provider,
        "chat_fallback_providers": global_settings.chat_fallback_providers,
        "draw_provider": global_settings.draw_provider,
        "draw_fallback_providers": global_settings.draw_fallback_providers,
        "providers": request.app.state.openrouter.list_providers(),
    }
