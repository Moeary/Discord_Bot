from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.schemas import (
    MinecraftBindingRequest,
    MinecraftChatEvent,
    MinecraftMessagesResponse,
    MinecraftOnlinePlayersResponse,
    MinecraftPendingTellsResponse,
    MinecraftPlayerEvent,
    MinecraftTellRequest,
)
from app.services.minecraft_bridge import is_valid_minecraft_username


router = APIRouter(prefix="/api/minecraft", tags=["minecraft"])


@router.post("/events/chat")
async def receive_minecraft_chat(request: Request, payload: MinecraftChatEvent) -> dict[str, object]:
    bridge = request.app.state.minecraft_bridge
    config = await bridge.verify_plugin_request(request, payload.server_id, action="chat")
    result = await bridge.publish_minecraft_chat(config, payload)
    return {"ok": True, **result}


@router.post("/events/player")
async def receive_minecraft_player_event(request: Request, payload: MinecraftPlayerEvent) -> dict[str, object]:
    bridge = request.app.state.minecraft_bridge
    config = await bridge.verify_plugin_request(request, payload.server_id, action="player_event")
    result = await bridge.publish_player_event(config, payload)
    return {"ok": True, **result}


@router.get("/servers/{server_id}/messages", response_model=MinecraftMessagesResponse)
async def poll_minecraft_messages(
    request: Request,
    server_id: str,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
) -> MinecraftMessagesResponse:
    bridge = request.app.state.minecraft_bridge
    await bridge.verify_plugin_request(request, server_id, action="poll")
    messages = await bridge.get_messages(server_id, after=after, limit=limit)
    next_after = max([after, *(message.id for message in messages)])
    return MinecraftMessagesResponse(messages=messages, next_after=next_after)


@router.get("/servers/{server_id}/status")
async def get_minecraft_server_status(request: Request, server_id: str) -> dict[str, object]:
    bridge = request.app.state.minecraft_bridge
    config = await bridge.get_guild_config(server_id)
    if config is None:
        raise HTTPException(status_code=404, detail="没有启用这个 Minecraft server_id 的服务器配置。")
    return {
        "guild_id": config.guild_id,
        "enabled": config.settings.minecraft_bridge_enabled,
        "server_address": config.settings.minecraft_server_address,
        "channel_id": config.settings.minecraft_channel_id,
        "server": bridge.get_server_status(server_id),
    }


@router.get("/servers/{server_id}/players")
async def get_online_players(request: Request, server_id: str) -> dict[str, object]:
    bridge = request.app.state.minecraft_bridge
    config = await bridge.get_guild_config(server_id)
    if config is None:
        raise HTTPException(status_code=404, detail="没有启用这个 Minecraft server_id 的服务器配置。")
    result = await bridge.get_online_players(server_id, config.settings)
    return result


@router.get("/bindings/{guild_id}")
async def list_minecraft_bindings(request: Request, guild_id: int) -> dict[str, object]:
    bindings = await request.app.state.store.list_minecraft_bindings(guild_id)
    return {"guild_id": guild_id, "bindings": bindings}


@router.put("/bindings/{guild_id}/{discord_user_id}")
async def set_minecraft_binding(
    request: Request,
    guild_id: int,
    discord_user_id: int,
    payload: MinecraftBindingRequest,
) -> dict[str, object]:
    if not is_valid_minecraft_username(payload.username):
        raise HTTPException(status_code=400, detail="Minecraft 用户名必须是 3-16 位字母、数字或下划线。")
    bindings = await request.app.state.store.set_minecraft_binding(guild_id, discord_user_id, payload.username)
    return {"guild_id": guild_id, "discord_user_id": str(discord_user_id), "username": payload.username, "bindings": bindings}


@router.delete("/bindings/{guild_id}/{discord_user_id}")
async def remove_minecraft_binding(request: Request, guild_id: int, discord_user_id: int) -> dict[str, object]:
    removed = await request.app.state.store.remove_minecraft_binding(guild_id, discord_user_id)
    return {"guild_id": guild_id, "discord_user_id": str(discord_user_id), "removed": removed}


@router.post("/servers/{server_id}/tells")
async def create_pending_tell(
    request: Request,
    server_id: str,
    payload: MinecraftTellRequest,
) -> dict[str, object]:
    bridge = request.app.state.minecraft_bridge
    config = await bridge.verify_plugin_request(request, server_id, action="tell_create")
    from_user = str(request.headers.get("x-tell-from-user", "DC"))
    tell = await bridge.add_pending_tell(server_id, payload.target_player, from_user, payload.message)
    return {"ok": True, "tell": tell.model_dump(mode="json")}


@router.get("/servers/{server_id}/tells/{player_name}", response_model=MinecraftPendingTellsResponse)
async def get_pending_tells(
    request: Request,
    server_id: str,
    player_name: str,
) -> MinecraftPendingTellsResponse:
    bridge = request.app.state.minecraft_bridge
    await bridge.verify_plugin_request(request, server_id, action="tells_fetch")
    tells = await bridge.clear_pending_tells(server_id, player_name)
    return MinecraftPendingTellsResponse(
        player_name=player_name,
        tells=[{"id": t.id, "from_user": t.from_user, "message": t.message, "created_at": t.created_at.isoformat()} for t in tells],
    )


@router.get("/servers/{server_id}/tells", response_model=dict[str, object])
async def list_pending_tell_players(request: Request, server_id: str) -> dict[str, object]:
    bridge = request.app.state.minecraft_bridge
    await bridge.verify_plugin_request(request, server_id, action="tells_list")
    players = await bridge.list_pending_tell_players(server_id)
    return {"server_id": server_id, "players_with_pending_tells": players}
