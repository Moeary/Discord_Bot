from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cached_property
from typing import Deque

import discord
import httpx
from fastapi import HTTPException, Request

from app.api.schemas import MinecraftChatEvent, MinecraftPlayerEvent, MinecraftQueuedMessage
from app.core.config import EnvSettings
from app.models.state import GuildSettings, MinecraftTell
from app.services.state_store import StateStore


LOGGER = logging.getLogger(__name__)
SERVER_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
MINECRAFT_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def is_valid_minecraft_username(username: str) -> bool:
    return bool(MINECRAFT_USERNAME_RE.fullmatch(username.strip()))


def sanitize_minecraft_username(name: str, fallback_id: int | str) -> str:
    sanitized = re.sub(r"\W+", "_", name.strip(), flags=re.ASCII).strip("_")
    if len(sanitized) > 16:
        sanitized = sanitized[:16]
    if len(sanitized) >= 3 and MINECRAFT_USERNAME_RE.fullmatch(sanitized):
        return sanitized
    suffix = str(fallback_id)[-10:]
    return f"dc_{suffix}"[:16]


@dataclass(frozen=True)
class MinecraftGuildConfig:
    guild_id: int
    settings: GuildSettings


class MinecraftBridge:
    def __init__(self, *, store: StateStore, bot: discord.Client, env: EnvSettings) -> None:
        self.store = store
        self.bot = bot
        self.env = env
        self._lock = asyncio.Lock()
        self._sequence = 0
        self._queues: dict[str, Deque[MinecraftQueuedMessage]] = defaultdict(lambda: deque(maxlen=300))
        self._rate_windows: dict[str, Deque[float]] = defaultdict(deque)
        self._last_seen: dict[str, dict[str, object]] = {}

    async def verify_plugin_request(
        self,
        request: Request,
        server_id: str,
        *,
        action: str,
    ) -> MinecraftGuildConfig:
        if not SERVER_ID_RE.fullmatch(server_id):
            raise HTTPException(status_code=400, detail="非法 Minecraft server_id。")

        config = await self.get_guild_config(server_id)
        if config is None:
            raise HTTPException(status_code=404, detail="没有启用这个 Minecraft server_id 的服务器配置。")

        host = request.client.host if request.client else ""
        self._check_rate_limit(server_id, host, action)
        self._verify_client_allowed(host)
        self._verify_token_or_local(request, config.settings, host)
        self._last_seen[server_id] = {
            "at": datetime.now(timezone.utc).isoformat(),
            "client_host": host,
            "action": action,
            "guild_id": config.guild_id,
        }
        return config

    async def get_guild_config(self, server_id: str) -> MinecraftGuildConfig | None:
        snapshot = await self.store.get_snapshot()
        matches: list[MinecraftGuildConfig] = []
        for guild_key, settings in snapshot.guilds.items():
            if not settings.minecraft_bridge_enabled:
                continue
            if settings.minecraft_server_id != server_id:
                continue
            try:
                guild_id = int(guild_key)
            except ValueError:
                continue
            matches.append(MinecraftGuildConfig(guild_id=guild_id, settings=settings))
        if matches:
            return sorted(matches, key=lambda item: item.guild_id)[0]
        if self.env.minecraft_bridge_enabled:
            if self.env.minecraft_server_id == server_id:
                return MinecraftGuildConfig(
                    guild_id=self._resolve_env_guild_id(),
                    settings=self._settings_from_env(),
                )
        return None

    def get_server_status(self, server_id: str) -> dict[str, object]:
        queue = self._queues.get(server_id)
        latest_id = queue[-1].id if queue else 0
        return {
            "server_id": server_id,
            "last_seen": self._last_seen.get(server_id),
            "queued_messages": len(queue or ()),
            "latest_message_id": latest_id,
        }

    async def publish_player_event(
        self,
        config: MinecraftGuildConfig,
        event: MinecraftPlayerEvent,
    ) -> dict[str, object]:
        if not config.settings.minecraft_channel_id:
            return {"accepted": False, "reason": "minecraft_channel_id_not_configured"}
        if not self.bot.is_ready():
            return {"accepted": False, "reason": "discord_bot_not_ready"}

        channel = self.bot.get_channel(config.settings.minecraft_channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(config.settings.minecraft_channel_id)
            except discord.HTTPException:
                channel = None
        if not isinstance(channel, discord.abc.Messageable):
            return {"accepted": False, "reason": "discord_channel_not_found"}

        player_name = sanitize_minecraft_username(event.player_name, event.player_uuid)
        if event.event_type == "join":
            emoji = "📥"
            action = "加入了服务器"
        elif event.event_type == "quit":
            emoji = "📤"
            action = "离开了服务器"
        else:
            return {"accepted": False, "reason": "unknown_event_type"}

        await channel.send(
            f"{emoji} **{discord.utils.escape_markdown(player_name)}** {action}",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return {"accepted": True}

    async def get_online_players(self, server_id: str, settings: GuildSettings) -> dict[str, object]:
        address = settings.minecraft_server_address
        if not address:
            return {"error": "minecraft_server_address not configured"}
        if "://" not in address:
            address = f"http://{address}"

        url = f"{address}/api/players"
        headers = {}
        token = settings.minecraft_token.strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["X-DC-Bot-Token"] = token

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    return resp.json()
                return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    async def add_pending_tell(
        self,
        server_id: str,
        target_player: str,
        from_user: str,
        message: str,
    ) -> MinecraftTell:
        return await self.store.add_pending_tell(server_id, target_player, from_user, message)

    async def get_pending_tells(self, server_id: str, player_name: str) -> list[MinecraftTell]:
        return await self.store.get_pending_tells(server_id, player_name)

    async def clear_pending_tells(self, server_id: str, player_name: str) -> list[MinecraftTell]:
        return await self.store.clear_pending_tells(server_id, player_name)

    async def list_pending_tell_players(self, server_id: str) -> dict[str, int]:
        return await self.store.list_pending_tell_players(server_id)

    def _settings_from_env(self) -> GuildSettings:
        return GuildSettings(
            minecraft_bridge_enabled=self.env.minecraft_bridge_enabled,
            minecraft_server_id=self.env.minecraft_server_id,
            minecraft_server_address=self.env.minecraft_server_address,
            minecraft_channel_id=self.env.minecraft_channel_id,
            minecraft_token=self.env.minecraft_token,
            minecraft_allow_no_token=self.env.minecraft_allow_no_token,
            minecraft_max_message_length=self.env.minecraft_max_message_length,
        )

    def _effective_settings_for_guild(
        self,
        guild_id: int,
        settings: GuildSettings,
        *,
        channel_id: int | None = None,
    ) -> GuildSettings:
        if settings.minecraft_bridge_enabled:
            return settings
        if not self.env.minecraft_bridge_enabled:
            return settings
        if self.env.minecraft_channel_id is not None and self.env.minecraft_channel_id == channel_id:
            return self._settings_from_env()
        env_guild_id = self._resolve_env_guild_id()
        if env_guild_id == guild_id:
            return self._settings_from_env()
        return settings

    def _resolve_env_guild_id(self) -> int:
        if self.env.minecraft_guild_id is not None:
            return self.env.minecraft_guild_id
        if self.env.discord_test_guild_id is not None:
            return self.env.discord_test_guild_id
        if self.env.minecraft_channel_id is not None:
            channel = self.bot.get_channel(self.env.minecraft_channel_id)
            guild = getattr(channel, "guild", None)
            guild_id = getattr(guild, "id", None)
            if isinstance(guild_id, int):
                return guild_id
        return 0

    async def publish_minecraft_chat(
        self,
        config: MinecraftGuildConfig,
        event: MinecraftChatEvent,
    ) -> dict[str, object]:
        content = self._clean_text(event.message, config.settings.minecraft_max_message_length)
        player_name = sanitize_minecraft_username(event.player_name, event.player_uuid)
        if not content:
            return {"accepted": False, "reason": "empty_message"}
        if not config.settings.minecraft_channel_id:
            return {"accepted": False, "reason": "minecraft_channel_id_not_configured"}
        if not self.bot.is_ready():
            return {"accepted": False, "reason": "discord_bot_not_ready"}

        channel = self.bot.get_channel(config.settings.minecraft_channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(config.settings.minecraft_channel_id)
            except discord.HTTPException:
                channel = None
        if not isinstance(channel, discord.abc.Messageable):
            LOGGER.warning(
                "Minecraft bridge could not resolve Discord channel %s for guild %s. "
                "Check MINECRAFT_CHANNEL_ID; it must be a text channel id, not a guild id.",
                config.settings.minecraft_channel_id,
                config.guild_id,
            )
            return {"accepted": False, "reason": "discord_channel_not_found"}

        await channel.send(
            f"`[MC]` **{discord.utils.escape_markdown(player_name)}**: {content}",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return {"accepted": True}

    async def enqueue_discord_message(self, message: discord.Message, settings: GuildSettings) -> bool:
        settings = self._effective_settings_for_guild(message.guild.id, settings, channel_id=message.channel.id)
        if not settings.minecraft_bridge_enabled or not settings.minecraft_channel_id:
            return False
        if message.channel.id != settings.minecraft_channel_id:
            return False
        if not settings.minecraft_server_id or not SERVER_ID_RE.fullmatch(settings.minecraft_server_id):
            return False

        content = self._clean_text(message.clean_content, settings.minecraft_max_message_length)
        attachment_urls = [attachment.url for attachment in message.attachments if attachment.url]
        if attachment_urls:
            content = self._clean_text("\n".join([content, *attachment_urls]).strip(), settings.minecraft_max_message_length)
        if not content:
            return False

        binding = await self.store.get_minecraft_binding(message.guild.id, message.author.id)
        username = (
            binding
            if binding and is_valid_minecraft_username(binding)
            else sanitize_minecraft_username(message.author.display_name, message.author.id)
        )
        queued = await self._append_message(
            settings.minecraft_server_id,
            username=username,
            display_name=message.author.display_name,
            discord_user_id=str(message.author.id),
            content=content,
        )
        return queued.id > 0

    async def get_messages(self, server_id: str, after: int, limit: int) -> list[MinecraftQueuedMessage]:
        limit = max(1, min(limit, 50))
        async with self._lock:
            queue = self._queues.get(server_id, deque())
            return [item for item in queue if item.id > after][:limit]

    async def _append_message(
        self,
        server_id: str,
        *,
        username: str,
        display_name: str,
        discord_user_id: str,
        content: str,
    ) -> MinecraftQueuedMessage:
        async with self._lock:
            self._sequence += 1
            queued = MinecraftQueuedMessage(
                id=self._sequence,
                username=username,
                display_name=display_name,
                discord_user_id=discord_user_id,
                content=content,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self._queues[server_id].append(queued)
            return queued

    def _verify_token_or_local(self, request: Request, settings: GuildSettings, host: str) -> None:
        configured_token = settings.minecraft_token.strip()
        provided_token = self._extract_token(request)
        if configured_token:
            if not provided_token or not secrets.compare_digest(provided_token, configured_token):
                raise HTTPException(status_code=401, detail="Minecraft bridge token 不正确。")
            return

        if not settings.minecraft_allow_no_token:
            raise HTTPException(status_code=401, detail="这个 Minecraft bridge 必须提供 token。")
        if not self._is_no_token_host_allowed(host):
            raise HTTPException(status_code=403, detail="未配置 token 时只允许本机或内网地址连接。")

    def _verify_client_allowed(self, host: str) -> None:
        allowed = self._allowed_client_networks
        if not allowed:
            return
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise HTTPException(status_code=403, detail="Minecraft bridge 来源地址不在白名单内。") from None
        if not any(address in network for network in allowed):
            raise HTTPException(status_code=403, detail="Minecraft bridge 来源地址不在白名单内。")

    @cached_property
    def _allowed_client_networks(self) -> tuple[ipaddress._BaseNetwork, ...]:
        items = [
            item.strip()
            for item in self.env.minecraft_allowed_clients.split(",")
            if item.strip()
        ]
        networks: list[ipaddress._BaseNetwork] = []
        for item in items:
            try:
                if "/" in item:
                    networks.append(ipaddress.ip_network(item, strict=False))
                else:
                    address = ipaddress.ip_address(item)
                    networks.append(ipaddress.ip_network(address.exploded, strict=False))
            except ValueError:
                continue
        return tuple(networks)

    @staticmethod
    def _extract_token(request: Request) -> str:
        header = request.headers.get("authorization", "").strip()
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        return request.headers.get("x-dc-bot-token", "").strip()

    @staticmethod
    def _is_no_token_host_allowed(host: str) -> bool:
        if host.lower() == "localhost":
            return True
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return address.is_loopback or address.is_private or address.is_link_local

    def _check_rate_limit(self, server_id: str, host: str, action: str) -> None:
        key = f"{server_id}:{host}:{action}"
        now = time.monotonic()
        window = self._rate_windows[key]
        while window and now - window[0] > 10:
            window.popleft()
        if len(window) >= 80:
            raise HTTPException(status_code=429, detail="Minecraft bridge 请求过快。")
        window.append(now)

    @staticmethod
    def _clean_text(text: str, max_length: int) -> str:
        cleaned = CONTROL_CHARS_RE.sub("", text or "").replace("\r", "").strip()
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        limit = max(1, min(max_length, 500))
        if len(cleaned) > limit:
            return f"{cleaned[: limit - 1]}…"
        return cleaned
