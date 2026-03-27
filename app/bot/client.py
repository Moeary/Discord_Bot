from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.core.catalog import GLOBAL_SETTING_SPECS, GUILD_SETTING_SPECS, cast_setting_value
from app.core.config import EnvSettings
from app.services.ai_router import ProfiledAIClient
from app.models.state import GuildSettings, TaxCase, UserImagePreferences, utcnow
from app.services.fun import FunService
from app.services.image_sources import ImageSourceRouter
from app.services.personas import PersonaStore
from app.services.saucenao import SauceNaoClient
from app.services.state_store import StateStore


LOGGER = logging.getLogger(__name__)
IMAGE_URL_RE = re.compile(r"https?://\S+\.(?:png|jpe?g|gif|webp)", re.IGNORECASE)
RATING_TAG_RE = re.compile(r"\brating:(?:s|q|e|safe|questionable|explicit|general)\b", re.IGNORECASE)
TAX_REPLY_KEYWORDS = {"税", "交税", "补税", "税务"}
SHIT_EMOJI_ALIASES = {"shit", "poop", "pile_of_poo", "💩"}
DIRECT_DRAW_PREFIXES = (
    "draw",
    "画",
    "画个",
    "画一张",
    "画张",
    "来张图",
    "来一张图",
    "生成图",
    "生成一张图",
    "绘图",
    "改图",
    "p图",
)
SAFE_IMAGE_KEYWORDS = ("来张美图", "来点美图", "来张好图", "来点好图", "来张老婆图", "来张图")
EXPLICIT_IMAGE_KEYWORDS = ("来张色图", "来点色图", "来张涩图", "来点涩图", "来张nsfw", "来点nsfw")
BOT_THINKING_GUARD = (
    "不要输出思考过程、不要输出推理草稿、不要输出<think>标签，"
    "只给最终答案。"
)


class EntertainmentBot(commands.Bot):
    def __init__(
        self,
        *,
        env: EnvSettings,
        store: StateStore,
        openrouter: ProfiledAIClient,
        image_sources: ImageSourceRouter,
        personas: PersonaStore,
        saucenao: SauceNaoClient,
    ) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.message_content = True
        intents.messages = True
        intents.reactions = True

        super().__init__(command_prefix="!", intents=intents)
        self.env = env
        self.store = store
        self.openrouter = openrouter
        self.image_sources = image_sources
        self.personas = personas
        self.saucenao = saucenao
        self._commands_registered = False
        self._synced = False

    async def setup_hook(self) -> None:
        if not self._commands_registered:
            self._register_commands()
            self._commands_registered = True
        if not self.tax_deadline_watcher.is_running():
            self.tax_deadline_watcher.start()

    async def on_ready(self) -> None:
        if not self._synced:
            if self.env.discord_test_guild_id:
                guild = discord.Object(id=self.env.discord_test_guild_id)
                # During development we register commands globally in the local
                # tree, then copy them into the test guild for instant updates.
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                LOGGER.info("Slash commands synced to test guild %s", self.env.discord_test_guild_id)
            else:
                await self.tree.sync()
                LOGGER.info("Global slash commands synced")
            self._synced = True
        LOGGER.info("Bot logged in as %s", self.user)

    def _register_commands(self) -> None:
        ai_group = app_commands.Group(name="ai", description="AI 功能")
        fun_group = app_commands.Group(name="fun", description="娱乐功能")
        config_group = app_commands.Group(
            name="config",
            description="配置功能",
            default_permissions=discord.Permissions(manage_guild=True),
        )

        @ai_group.command(name="chat", description="和 AI 聊天")
        @app_commands.describe(
            prompt="你想让 AI 回复的内容",
            image="可选：附带一张图片给 AI 一起看",
            profile="可选：指定聊天模型档案名，例如 grsai-gemini-3.1-pro",
        )
        async def ai_chat(
            interaction: discord.Interaction,
            prompt: str,
            image: discord.Attachment | None = None,
            profile: str | None = None,
        ) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.ai_enabled:
                await interaction.response.send_message("这个服务器没有开启 AI 功能。", ephemeral=True)
                return

            await interaction.response.defer()
            global_settings = await self.store.get_global_settings()
            image_urls: list[str] = []
            if image is not None and self._attachment_is_image(image):
                image_urls.append(image.url)
            messages = [
                {
                    "role": "system",
                    "content": self._compose_ai_system_prompt(
                        self._resolve_system_prompt(global_settings),
                        global_settings,
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_user_multimodal_content(
                        f"{interaction.user.display_name}: {prompt}",
                        image_urls,
                        empty_text_fallback=f"{interaction.user.display_name}: 请结合图片内容回复。",
                    ),
                },
            ]
            try:
                reply = await self.openrouter.chat(
                    messages,
                    profile=profile or global_settings.chat_model_profile,
                    fallback_profiles=global_settings.chat_fallback_profiles,
                )
            except Exception as exc:  # pragma: no cover - network bound
                await interaction.followup.send(f"AI 调用失败：{self._describe_error(exc)}")
                return

            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "ai_calls")
            await self._send_followup_chunks(interaction, reply)

        @ai_group.command(name="summary", description="总结当前频道最近聊天")
        @app_commands.describe(limit="读取多少条消息，默认按服务器配置")
        async def ai_summary(interaction: discord.Interaction, limit: int | None = None) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.ai_enabled:
                await interaction.response.send_message("这个服务器没有开启 AI 功能。", ephemeral=True)
                return

            await interaction.response.defer()
            global_settings = await self.store.get_global_settings()
            target_limit = max(5, min(limit or guild_settings.summary_limit, 100))
            transcript = await self._build_summary_transcript(
                interaction.channel,
                target_limit,
                include_image_hints=False,
            )
            if not transcript.strip():
                await interaction.followup.send("当前频道最近没有足够内容可以总结。")
                return

            try:
                reply = await self.openrouter.summarize_text(
                    self._compose_ai_system_prompt(
                        self._resolve_summary_prompt(global_settings),
                        global_settings,
                    ),
                    transcript,
                    profile=global_settings.chat_model_profile,
                    fallback_profiles=global_settings.chat_fallback_profiles,
                )
            except Exception as exc:  # pragma: no cover - network bound
                await interaction.followup.send(f"AI 总结失败：{self._describe_error(exc)}")
                return

            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "ai_calls")
            await self._send_followup_chunks(interaction, reply)

        @ai_group.command(name="draw", description="AI 绘图")
        @app_commands.describe(
            prompt="你想生成或改图的描述，可留空让系统按参考图自动补一句",
            profile="可选：指定绘图模型档案名，例如 grsai-sora-image / grsai-banana2",
            model="可选：临时覆盖档案内的模型名",
            size="可选：比例参数。Sora/GPT 用 size，Banana 档案会把它当 aspectRatio",
            variants="可选：生成张数 1 或 2",
            image="可选：参考图",
        )
        async def ai_draw(
            interaction: discord.Interaction,
            prompt: str | None = None,
            profile: str | None = None,
            model: str | None = None,
            size: str = "1:1",
            variants: app_commands.Range[int, 1, 2] = 1,
            image: discord.Attachment | None = None,
        ) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.ai_enabled:
                await interaction.response.send_message("这个服务器没有开启 AI 功能。", ephemeral=True)
                return

            await interaction.response.defer(thinking=True)
            global_settings = await self.store.get_global_settings()
            draw_profile = profile or getattr(global_settings, "draw_model_profile", "legacy-draw")
            urls: list[str] = []
            if image is not None and self._attachment_is_image(image):
                urls.append(image.url)
            prompt_text = (prompt or "").strip()
            if not prompt_text and urls:
                prompt_text = "请基于提供的图片做一次高质量改图，保留主体、角色特征和关键细节。"
            if not prompt_text:
                await interaction.followup.send("想让我画图的话，至少给一句描述，或者附上一张参考图。")
                return

            try:
                result = await self.openrouter.draw(
                    prompt=prompt_text,
                    model=model or None,
                    profile=draw_profile,
                    fallback_profiles=global_settings.draw_fallback_profiles,
                    size=size,
                    variants=variants,
                    urls=urls,
                )
                resolved = await self._await_draw_completion(result)
            except Exception as exc:  # pragma: no cover - network bound
                await interaction.followup.send(f"绘图失败：{self._describe_error(exc)}")
                return

            images = self._extract_draw_result_urls(resolved)
            if not images:
                await interaction.followup.send(f"绘图任务已返回，但没有图片地址：{resolved}")
                return

            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "ai_calls")
            header_parts = [
                f"档案: `{result.get('_profile', draw_profile)}`",
                f"比例: `{size}`",
                f"数量: `{len(images)}`",
            ]
            if result.get("_warning"):
                header_parts.append(str(result["_warning"]))
            header = " | ".join(header_parts)
            await interaction.followup.send("\n".join([header, *images]))

        @ai_group.command(name="image", description="AI 画图（/ai draw 别名）")
        @app_commands.describe(
            prompt="你想生成或改图的描述，可留空让系统按参考图自动补一句",
            profile="可选：指定绘图模型档案名，例如 grsai-sora-image / grsai-banana2",
            model="可选：临时覆盖档案内的模型名",
            size="可选：比例参数",
            variants="可选：生成张数 1 或 2",
            image="可选：参考图",
        )
        async def ai_image(
            interaction: discord.Interaction,
            prompt: str | None = None,
            profile: str | None = None,
            model: str | None = None,
            size: str = "1:1",
            variants: app_commands.Range[int, 1, 2] = 1,
            image: discord.Attachment | None = None,
        ) -> None:
            await ai_draw(interaction, prompt, profile, model, size, variants, image)

        @fun_group.command(name="image", description="让系统替你捞一张图，按当前图站档案处理")
        @app_commands.describe(
            style="safe 表示美图，explicit 表示涩图",
            tags="额外标签，例如 1girl blue_hair",
            profile="可选：临时指定图站档案，例如 danbooru / rule34",
        )
        async def fun_image(
            interaction: discord.Interaction,
            style: str = "safe",
            tags: str | None = None,
            profile: str | None = None,
        ) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            rating_mode = self._normalize_image_style(style)
            if rating_mode is None:
                await interaction.response.send_message("style 只能是 `safe` 或 `explicit`。", ephemeral=True)
                return
            if rating_mode == "explicit" and not self._channel_is_nsfw(interaction.channel):
                await interaction.response.send_message("涩图去 NSFW 频道叫我。", ephemeral=True)
                return

            await interaction.response.defer(thinking=True)
            try:
                embed = await self._build_image_response_embed(
                    guild_settings=guild_settings,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    rating_mode=rating_mode,
                    extra_tags=tags or "",
                    profile_override=profile,
                )
            except Exception as exc:  # pragma: no cover - network bound
                await interaction.followup.send(f"图站请求失败：{self._describe_error(exc)}")
                return

            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "danbooru_calls")
            await interaction.followup.send(embed=embed)

        @fun_group.command(name="danbooru", description="固定从 Danbooru 捞一张图")
        @app_commands.describe(tags="额外标签，例如 1girl blue_hair")
        async def fun_danbooru(interaction: discord.Interaction, tags: str | None = None) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            await interaction.response.defer(thinking=True)
            try:
                embed = await self._build_image_response_embed(
                    guild_settings=guild_settings,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    rating_mode="explicit" if self._channel_is_nsfw(interaction.channel) else "safe",
                    extra_tags=tags or "",
                    profile_override="danbooru",
                )
            except Exception as exc:  # pragma: no cover - network bound
                await interaction.followup.send(f"图站请求失败：{self._describe_error(exc)}")
                return

            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "danbooru_calls")
            await interaction.followup.send(embed=embed)

        @fun_group.command(name="rule34", description="固定从 Rule34 捞一张涩图")
        @app_commands.describe(tags="额外标签，例如 bunny_girl azur_lane")
        async def fun_rule34(interaction: discord.Interaction, tags: str | None = None) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return
            if not self._channel_is_nsfw(interaction.channel):
                await interaction.response.send_message("Rule34 也请去 NSFW 频道叫我。", ephemeral=True)
                return

            await interaction.response.defer(thinking=True)
            try:
                embed = await self._build_image_response_embed(
                    guild_settings=guild_settings,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    rating_mode="explicit",
                    extra_tags=tags or "",
                    profile_override="rule34",
                )
            except Exception as exc:  # pragma: no cover - network bound
                await interaction.followup.send(f"图站请求失败：{self._describe_error(exc)}")
                return

            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "danbooru_calls")
            await interaction.followup.send(embed=embed)

        @fun_group.command(name="pretty", description="请求一张勉强适合公开展示的美图")
        @app_commands.describe(tags="额外标签，例如 1girl blue_hair", profile="可选：临时指定图站档案")
        async def fun_pretty(
            interaction: discord.Interaction,
            tags: str | None = None,
            profile: str | None = None,
        ) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            await interaction.response.defer(thinking=True)
            try:
                embed = await self._build_image_response_embed(
                    guild_settings=guild_settings,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    rating_mode="safe",
                    extra_tags=tags or "",
                    profile_override=profile,
                )
            except Exception as exc:  # pragma: no cover - network bound
                await interaction.followup.send(f"图站请求失败：{self._describe_error(exc)}")
                return

            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "danbooru_calls")
            await interaction.followup.send(embed=embed)

        @fun_group.command(name="lewd", description="请求一张需要 NSFW 频道兜底的涩图")
        @app_commands.describe(tags="额外标签，例如 azur_lane bunny_girl", profile="可选：临时指定图站档案")
        async def fun_lewd(
            interaction: discord.Interaction,
            tags: str | None = None,
            profile: str | None = None,
        ) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return
            if not self._channel_is_nsfw(interaction.channel):
                await interaction.response.send_message("涩图去 NSFW 频道叫我。", ephemeral=True)
                return

            await interaction.response.defer(thinking=True)
            try:
                embed = await self._build_image_response_embed(
                    guild_settings=guild_settings,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    rating_mode="explicit",
                    extra_tags=tags or "",
                    profile_override=profile,
                )
            except Exception as exc:  # pragma: no cover - network bound
                await interaction.followup.send(f"图站请求失败：{self._describe_error(exc)}")
                return

            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "danbooru_calls")
            await interaction.followup.send(embed=embed)

        @fun_group.command(name="image_prefs", description="查看你自己的图站偏好")
        async def fun_image_prefs(interaction: discord.Interaction) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            preferences = await self.store.get_user_preferences(interaction.guild_id, interaction.user.id)
            lines = [
                f"`safe_image_site_profile`: {preferences.safe_image_site_profile or guild_settings.safe_image_site_profile}",
                f"`explicit_image_site_profile`: {preferences.explicit_image_site_profile or guild_settings.explicit_image_site_profile}",
                f"`safe_image_tags`: {preferences.safe_image_tags or guild_settings.safe_image_default_tags or '-'}",
                f"`explicit_image_tags`: {preferences.explicit_image_tags or guild_settings.explicit_image_default_tags or '-'}",
            ]
            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        @fun_group.command(name="image_source", description="设置你自己的美图/涩图默认图站")
        @app_commands.describe(style="safe 表示美图，explicit 表示涩图", profile="图站档案名，例如 danbooru / rule34")
        async def fun_image_source(interaction: discord.Interaction, style: str, profile: str) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            rating_mode = self._normalize_image_style(style)
            if rating_mode is None:
                await interaction.response.send_message("style 只能是 `safe` 或 `explicit`。", ephemeral=True)
                return
            available_profiles = self.image_sources.list_profiles()
            if profile not in available_profiles:
                await interaction.response.send_message(
                    f"未知图站档案。可选：{', '.join(sorted(available_profiles))}",
                    ephemeral=True,
                )
                return
            capability_key = "supports_safe" if rating_mode == "safe" else "supports_explicit"
            if not available_profiles[profile].get(capability_key):
                await interaction.response.send_message(
                    f"`{profile}` 不支持当前模式 `{rating_mode}`。",
                    ephemeral=True,
                )
                return
            target_key = "safe_image_site_profile" if rating_mode == "safe" else "explicit_image_site_profile"
            updated = await self.store.update_user_preferences(interaction.guild_id, interaction.user.id, {target_key: profile})
            await interaction.response.send_message(
                f"已更新你的 `{target_key}` -> `{getattr(updated, target_key)}`",
                ephemeral=True,
            )

        @fun_group.command(name="image_tags", description="设置你自己的美图/涩图默认 tag")
        @app_commands.describe(style="safe 表示美图，explicit 表示涩图", tags="输入标签；填 clear / none / - 可以清空")
        async def fun_image_tags(interaction: discord.Interaction, style: str, tags: str) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            rating_mode = self._normalize_image_style(style)
            if rating_mode is None:
                await interaction.response.send_message("style 只能是 `safe` 或 `explicit`。", ephemeral=True)
                return
            normalized_tags = "" if tags.strip().lower() in {"clear", "none", "-"} else tags.strip()
            target_key = "safe_image_tags" if rating_mode == "safe" else "explicit_image_tags"
            updated = await self.store.update_user_preferences(
                interaction.guild_id,
                interaction.user.id,
                {target_key: normalized_tags},
            )
            await interaction.response.send_message(
                f"已更新你的 `{target_key}` -> `{getattr(updated, target_key) or '-'}`",
                ephemeral=True,
            )

        @fun_group.command(name="image_sites", description="列出当前可用的图站档案")
        async def fun_image_sites(interaction: discord.Interaction) -> None:
            profiles = self.image_sources.list_profiles()
            lines = []
            for name, item in sorted(profiles.items()):
                support = []
                if item.get("supports_safe"):
                    support.append("safe")
                if item.get("supports_explicit"):
                    support.append("explicit")
                lines.append(f"`{name}` | 支持: {', '.join(support) or '-'} | {item.get('description', '')}")
            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        @fun_group.command(name="sauce", description="用 SauceNAO 反查图片来源")
        @app_commands.describe(
            image="可选：直接附一张图",
            url="可选：直接贴图片 URL",
        )
        async def fun_sauce(
            interaction: discord.Interaction,
            image: discord.Attachment | None = None,
            url: str | None = None,
        ) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            image_url = url.strip() if url and url.strip() else None
            if image_url is None and image is not None and self._attachment_is_image(image):
                image_url = image.url
            if image_url is None:
                await interaction.response.send_message("给我一张图或者一个图片 URL，我才有东西可查。", ephemeral=True)
                return

            await interaction.response.defer(thinking=True, ephemeral=True)
            try:
                payload = await self.saucenao.search(image_url)
            except Exception as exc:  # pragma: no cover - network bound
                await interaction.followup.send(f"SauceNAO 搜图失败：{self._describe_error(exc)}", ephemeral=True)
                return

            embed = self._build_saucenao_embed(payload, image_url)
            await interaction.followup.send(embed=embed, ephemeral=True)

        @fun_group.command(name="fortune", description="查看今日系统运势评估")
        async def fun_fortune(interaction: discord.Interaction) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            global_settings = await self.store.get_global_settings()
            result = FunService.daily_fortune(
                interaction.user.id,
                interaction.guild_id,
                config=self._get_fun_payload(global_settings),
            )
            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "fortune_calls")
            await interaction.response.send_message(
                f"{interaction.user.mention} 今日运势评估：`{result['score']}/100`\n{result['text']}"
            )

        @fun_group.command(name="roulette", description="进行一次毫无必要的轮盘实验")
        async def fun_roulette(interaction: discord.Interaction) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            global_settings = await self.store.get_global_settings()
            result = FunService.roulette(config=self._get_fun_payload(global_settings))
            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "roulette_calls")
            await interaction.response.send_message(
                f"{interaction.user.mention} 扣下扳机……\n{result['text']} (弹仓位置: {result['chamber']}/6)"
            )

        @fun_group.command(name="coin", description="把你的决策权外包给一枚硬币")
        async def fun_coin(interaction: discord.Interaction) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            global_settings = await self.store.get_global_settings()
            result = FunService.coinflip(
                interaction.user.id,
                interaction.guild_id,
                config=self._get_fun_payload(global_settings),
            )
            await interaction.response.send_message(
                f"{interaction.user.mention} {result['text']}\n结果：`{result['side']}`"
            )

        @fun_group.command(name="choose", description="让系统替你做一个懒惰但有效的选择")
        @app_commands.describe(options="用 | 分隔多个选项，例如 火锅 | 烤肉 | 麻辣烫")
        async def fun_choose(interaction: discord.Interaction, options: str) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            try:
                global_settings = await self.store.get_global_settings()
                result = FunService.choose(
                    options.split("|"),
                    interaction.guild_id,
                    interaction.user.id,
                    config=self._get_fun_payload(global_settings),
                )
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return

            await interaction.response.send_message(
                f"{interaction.user.mention} 我替你做了决定：`{result['choice']}`\n"
                "你大可以把责任推给我。反正你本来也会这么做。"
            )

        @fun_group.command(name="eightball", description="让系统对你的是非题做一次冷酷裁决")
        @app_commands.describe(question="例如：我今天该不该熬夜？")
        async def fun_eightball(interaction: discord.Interaction, question: str) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            global_settings = await self.store.get_global_settings()
            result = FunService.eight_ball(
                question,
                interaction.guild_id,
                interaction.user.id,
                config=self._get_fun_payload(global_settings),
            )
            await interaction.response.send_message(
                f"{interaction.user.mention} 问题：{question}\n回答：{result['answer']}"
            )

        @fun_group.command(name="waifu", description="抽取你今天的危险情感投射对象")
        async def fun_waifu(interaction: discord.Interaction) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            members = [member for member in interaction.guild.members if not member.bot]
            target_id = FunService.pick_waifu(
                [member.id for member in members],
                interaction.guild_id,
                interaction.user.id,
                utcnow().strftime("%Y-%m-%d"),
            )
            if target_id is None:
                await interaction.response.send_message("服务器里没有可选成员。", ephemeral=True)
                return
            target = interaction.guild.get_member(target_id)
            await interaction.response.send_message(
                f"{interaction.user.mention} 今日命中目标：{target.mention if target else target_id}\n"
                "请谨慎处理这段被系统强行安排的关系。"
            )

        @fun_group.command(name="lottery", description="领取今日签运和廉价命运解读")
        async def fun_lottery(interaction: discord.Interaction) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            global_settings = await self.store.get_global_settings()
            result = FunService.lottery(
                interaction.user.id,
                interaction.guild_id,
                config=self._get_fun_payload(global_settings),
            )
            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "lottery_calls")
            await interaction.response.send_message(
                f"{interaction.user.mention} 今日签运点数：`{result['roll']}`\n"
                f"稀有度：`{result['rarity']}`\n{result['text']}\n{result['omen']}"
            )

        @fun_group.command(name="ship", description="测量两名测试对象的电波同步率")
        @app_commands.describe(member_a="第一个人", member_b="第二个人")
        async def fun_ship(
            interaction: discord.Interaction,
            member_a: discord.Member,
            member_b: discord.Member,
        ) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            global_settings = await self.store.get_global_settings()
            result = FunService.ship_score(
                member_a.id,
                member_b.id,
                interaction.guild_id,
                utcnow().strftime("%Y-%m-%d"),
                config=self._get_fun_payload(global_settings),
            )
            await interaction.response.send_message(
                f"{member_a.mention} x {member_b.mention}\n"
                f"同步率：`{result['score']}%`\n{result['label']}"
            )

        @fun_group.command(name="diagnose", description="对某个对象做一次情绪稳定性诊断")
        @app_commands.describe(target="你要诊断的人、事、物，或者一段短文本")
        async def fun_diagnose(interaction: discord.Interaction, target: str) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            global_settings = await self.store.get_global_settings()
            result = FunService.diagnose(
                target,
                interaction.guild_id,
                interaction.user.id,
                config=self._get_fun_payload(global_settings),
            )
            await interaction.response.send_message(
                f"`{target}` 的稳定性诊断：`{result['score']}/100`\n"
                f"结论：`{result['label']}`\n{result['note']}"
            )

        @fun_group.command(name="rate", description="让系统对某个东西打分")
        @app_commands.describe(subject="要评分的对象，例如 这周作业 / 这张图 / 我的睡眠")
        async def fun_rate(interaction: discord.Interaction, subject: str) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            global_settings = await self.store.get_global_settings()
            result = FunService.rate(
                subject,
                interaction.guild_id,
                interaction.user.id,
                config=self._get_fun_payload(global_settings),
            )
            await interaction.response.send_message(
                f"`{subject}` 的评分：`{result['score']}/100`\n"
                f"等级：`{result['label']}`\n{result['note']}"
            )

        @fun_group.command(name="duel", description="模拟两名测试对象之间的荒谬决斗")
        @app_commands.describe(challenger="挑战者", defender="被挑战者")
        async def fun_duel(
            interaction: discord.Interaction,
            challenger: discord.Member,
            defender: discord.Member,
        ) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            global_settings = await self.store.get_global_settings()
            result = FunService.duel(
                challenger.id,
                defender.id,
                interaction.guild_id,
                utcnow().strftime("%Y-%m-%d"),
                config=self._get_fun_payload(global_settings),
            )
            winner = challenger if result["winner_id"] == challenger.id else defender
            await interaction.response.send_message(
                f"{challenger.mention} vs {defender.mention}\n"
                f"胜者：{winner.mention}\n"
                f"压制幅度：`{result['margin']}%`\n{result['flavor']}"
            )

        @fun_group.command(name="leaderboard", description="查看本群娱乐与事故贡献排行榜")
        async def fun_leaderboard(interaction: discord.Interaction) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            snapshot = await self.store.get_snapshot()
            guild_stats = snapshot.stats.get(str(interaction.guild_id))
            if not guild_stats or not guild_stats.user_stats:
                await interaction.response.send_message("还没有统计数据。")
                return

            ranking = sorted(
                guild_stats.user_stats.items(),
                key=lambda item: (
                    item[1].warnings + item[1].ai_calls + item[1].danbooru_calls,
                    item[1].taxes_paid,
                ),
                reverse=True,
            )[:10]
            lines = []
            for index, (user_id, stats) in enumerate(ranking, start=1):
                member = interaction.guild.get_member(int(user_id))
                name = member.display_name if member else f"User {user_id}"
                lines.append(
                    f"{index}. {name} | 警告 {stats.warnings} | 已交税 {stats.taxes_paid} | "
                    f"AI {stats.ai_calls} | 色图 {stats.danbooru_calls} | 抽签 {stats.lottery_calls}"
                )
            await interaction.response.send_message("\n".join(lines))

        @config_group.command(name="view", description="查看配置，可选 guild / global / all")
        @app_commands.describe(scope="guild / global / all，默认 all")
        async def config_view(interaction: discord.Interaction, scope: str = "all") -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            global_settings = await self.store.get_global_settings()
            normalized_scope = scope.strip().lower()
            if normalized_scope not in {"all", "guild", "global"}:
                await interaction.response.send_message("scope 只能是 `guild` / `global` / `all`。", ephemeral=True)
                return
            sections: list[str] = []
            if normalized_scope in {"all", "guild"}:
                sections.append(
                    "\n".join(
                        [
                            "[Guild]",
                            f"`ai_enabled`: {guild_settings.ai_enabled}",
                            f"`fun_enabled`: {guild_settings.fun_enabled}",
                            f"`tax_enabled`: {guild_settings.tax_enabled}",
                            f"`tax_channel_id`: {guild_settings.tax_channel_id}",
                            f"`log_channel_id`: {guild_settings.log_channel_id}",
                            f"`shit_emoji`: {guild_settings.shit_emoji}",
                            f"`tax_required_images`: {guild_settings.tax_required_images}",
                            f"`tax_payment_window_minutes`: {guild_settings.tax_payment_window_minutes}",
                            f"`mute_hours`: {guild_settings.mute_hours}",
                            f"`summary_limit`: {guild_settings.summary_limit}",
                            f"`danbooru_default_tags`: {guild_settings.danbooru_default_tags}",
                            f"`safe_image_site_profile`: {guild_settings.safe_image_site_profile}",
                            f"`explicit_image_site_profile`: {guild_settings.explicit_image_site_profile}",
                            f"`safe_image_default_tags`: {guild_settings.safe_image_default_tags or '-'}",
                            f"`explicit_image_default_tags`: {guild_settings.explicit_image_default_tags or '-'}",
                        ]
                    )
                )
            if normalized_scope in {"all", "global"}:
                sections.append(
                    "\n".join(
                        [
                            "[Global]",
                            f"`persona_profile`: {getattr(global_settings, 'persona_profile', 'glados')}",
                            f"`chat_model_profile`: {global_settings.chat_model_profile}",
                            f"`chat_fallback_profiles`: {global_settings.chat_fallback_profiles or '-'}",
                            f"`draw_model_profile`: {global_settings.draw_model_profile}",
                            f"`draw_fallback_profiles`: {global_settings.draw_fallback_profiles or '-'}",
                            f"`max_chat_history`: {global_settings.max_chat_history}",
                        ]
                    )
                )
            text = "\n\n".join(sections)
            await interaction.response.send_message(text, ephemeral=True)

        @config_group.command(name="global_view", description="查看全局 AI 配置")
        async def config_global_view(interaction: discord.Interaction) -> None:
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message("需要管理服务器权限。", ephemeral=True)
                return
            await config_view(interaction, "global")

        @config_group.command(name="global_set", description="修改全局 AI 配置")
        @app_commands.describe(key="全局配置项名", value="配置值")
        async def config_global_set(interaction: discord.Interaction, key: str, value: str) -> None:
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message("需要管理服务器权限。", ephemeral=True)
                return
            await config_set(interaction, key, value, "global")

        @config_group.command(name="set", description="设置配置项，可选 guild / global")
        @app_commands.describe(scope="guild / global，默认 guild", key="配置项名", value="配置值")
        async def config_set(interaction: discord.Interaction, key: str, value: str, scope: str = "guild") -> None:
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message("需要管理服务器权限。", ephemeral=True)
                return
            normalized_scope = scope.strip().lower()
            if normalized_scope == "global":
                if key not in GLOBAL_SETTING_SPECS:
                    await interaction.response.send_message(
                        f"未知全局配置项。可选：{', '.join(GLOBAL_SETTING_SPECS.keys())}",
                        ephemeral=True,
                    )
                    return
                try:
                    cast_value = cast_setting_value(GLOBAL_SETTING_SPECS, key, value)
                except Exception as exc:
                    await interaction.response.send_message(f"配置值不合法：{exc}", ephemeral=True)
                    return
                settings = await self.store.update_global_settings({key: cast_value})
                await interaction.response.send_message(
                    f"已更新全局 `{key}` -> `{getattr(settings, key)}`",
                    ephemeral=True,
                )
                return

            if normalized_scope != "guild":
                await interaction.response.send_message("scope 只能是 `guild` 或 `global`。", ephemeral=True)
                return
            if key not in GUILD_SETTING_SPECS:
                await interaction.response.send_message(
                    f"未知服务器配置项。可选：{', '.join(GUILD_SETTING_SPECS.keys())}",
                    ephemeral=True,
                )
                return
            try:
                cast_value = cast_setting_value(GUILD_SETTING_SPECS, key, value)
            except Exception as exc:
                await interaction.response.send_message(f"配置值不合法：{exc}", ephemeral=True)
                return

            settings = await self.store.update_guild_settings(
                interaction.guild_id,
                {key: cast_value},
                guild_name=interaction.guild.name,
            )
            await interaction.response.send_message(
                f"已更新 `{key}` -> `{getattr(settings, key)}`",
                ephemeral=True,
            )

        @config_group.command(name="tax_channel", description="设置税务频道")
        @app_commands.describe(channel="要作为补税频道的频道")
        async def config_tax_channel(
            interaction: discord.Interaction,
            channel: discord.TextChannel,
        ) -> None:
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message("需要管理服务器权限。", ephemeral=True)
                return
            await self.store.update_guild_settings(
                interaction.guild_id,
                {"tax_channel_id": channel.id},
                guild_name=interaction.guild.name,
            )
            await interaction.response.send_message(f"税务频道已设置为 {channel.mention}", ephemeral=True)

        @app_commands.context_menu(name="GLaDOS 改图")
        async def message_redraw(interaction: discord.Interaction, target: discord.Message) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.ai_enabled:
                await interaction.response.send_message("这个服务器没有开启 AI 功能。", ephemeral=True)
                return

            urls = self._extract_image_urls_from_message(target)
            if not urls:
                await interaction.response.send_message("这条消息里没有可用图片。", ephemeral=True)
                return

            await interaction.response.defer(thinking=True)
            global_settings = await self.store.get_global_settings()
            prompt_text = target.content.strip() or "请基于提供的图片做一次高质量改图，保留主体、角色特征和关键细节。"
            try:
                result = await self.openrouter.draw(
                    prompt=prompt_text,
                    profile=getattr(global_settings, "draw_model_profile", "legacy-draw"),
                    fallback_profiles=getattr(global_settings, "draw_fallback_profiles", ""),
                    size="1:1",
                    variants=1,
                    urls=urls,
                )
                resolved = await self._await_draw_completion(result)
            except Exception as exc:  # pragma: no cover - network bound
                await interaction.followup.send(f"绘图失败：{self._describe_error(exc)}")
                return

            images = self._extract_draw_result_urls(resolved)
            if not images:
                await interaction.followup.send(f"绘图任务回来了，但没吐出图片地址：{resolved}")
                return

            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "ai_calls")
            await interaction.followup.send("\n".join(images))

        @app_commands.context_menu(name="GLaDOS 搜图")
        async def message_sauce(interaction: discord.Interaction, target: discord.Message) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            image_urls = self._extract_image_urls_from_message(target)
            if not image_urls:
                await interaction.response.send_message("这条消息里没有可用图片。", ephemeral=True)
                return

            await interaction.response.defer(thinking=True, ephemeral=True)
            try:
                payload = await self.saucenao.search(image_urls[0])
            except Exception as exc:  # pragma: no cover - network bound
                await interaction.followup.send(f"SauceNAO 搜图失败：{self._describe_error(exc)}", ephemeral=True)
                return
            await interaction.followup.send(embed=self._build_saucenao_embed(payload, image_urls[0]), ephemeral=True)

        self.tree.add_command(ai_group)
        self.tree.add_command(fun_group)
        self.tree.add_command(config_group)
        self.tree.add_command(message_redraw)
        self.tree.add_command(message_sauce)

    async def _require_guild_settings(
        self,
        interaction: discord.Interaction,
    ) -> GuildSettings | None:
        if interaction.guild is None or interaction.guild_id is None:
            await interaction.response.send_message("这个命令只能在服务器内使用。", ephemeral=True)
            return None
        return await self.store.get_guild_settings(interaction.guild_id, interaction.guild.name)

    async def _build_chat_history(
        self,
        channel: discord.abc.Messageable | None,
        limit: int,
    ) -> list[dict[str, str]]:
        if channel is None or not hasattr(channel, "history"):
            return []

        history: list[dict[str, str]] = []
        async for message in channel.history(limit=limit):
            if message.author.bot or not message.content.strip():
                continue
            role = "assistant" if self.user and message.author.id == self.user.id else "user"
            history.append({"role": role, "content": f"{message.author.display_name}: {message.content}"})
        history.reverse()
        return history

    def _get_persona_payload(self, persona_profile: str | None) -> dict[str, object]:
        return self.personas.get_persona(persona_profile)

    def _get_fun_payload(self, global_settings) -> dict[str, object]:
        persona = self._get_persona_payload(getattr(global_settings, "persona_profile", "glados"))
        fun_payload = persona.get("fun")
        return fun_payload if isinstance(fun_payload, dict) else {}

    def _resolve_system_prompt(self, global_settings) -> str:
        persona = self._get_persona_payload(getattr(global_settings, "persona_profile", "glados"))
        return str(persona.get("system_prompt", "")).strip()

    def _resolve_summary_prompt(self, global_settings) -> str:
        persona = self._get_persona_payload(getattr(global_settings, "persona_profile", "glados"))
        return str(persona.get("summary_system_prompt", "")).strip()

    def _compose_ai_system_prompt(self, base_prompt: str, global_settings) -> str:
        persona = self._get_persona_payload(getattr(global_settings, "persona_profile", "glados"))
        thinking_guard = str(persona.get("thinking_guard", "")).strip() or BOT_THINKING_GUARD
        return f"{base_prompt}\n{thinking_guard}"

    async def _resolve_referenced_message(self, message: discord.Message) -> discord.Message | None:
        if not message.reference:
            return None
        referenced = message.reference.resolved
        if referenced is None and message.reference.message_id:
            try:
                referenced = await message.channel.fetch_message(message.reference.message_id)
            except discord.HTTPException:
                referenced = None
        return referenced if isinstance(referenced, discord.Message) else None

    async def _build_summary_transcript(
        self,
        channel: discord.abc.Messageable | None,
        limit: int,
        include_image_hints: bool = False,
    ) -> str:
        if channel is None or not hasattr(channel, "history"):
            return ""
        lines: list[str] = []
        async for message in channel.history(limit=limit):
            content = message.content.strip()
            if not content and not message.attachments:
                continue
            attachment_hint = ""
            if include_image_hints and message.attachments:
                attachment_hint = " [附带图片/文件]"
            lines.append(f"{message.author.display_name}: {content or '[无文字]'}{attachment_hint}")
        lines.reverse()
        return "\n".join(lines)

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or self.user is None or payload.user_id == self.user.id:
            return
        guild = self.get_guild(payload.guild_id)
        if guild is None:
            return

        settings = await self.store.get_guild_settings(guild.id, guild.name)
        if not settings.tax_enabled or not self._is_shit_emoji(settings.shit_emoji, payload.emoji):
            return

        channel = guild.get_channel(payload.channel_id)
        if channel is None or not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return
        await self._try_create_tax_case(
            guild=guild,
            source_channel=channel,
            target_message=message,
            triggered_by_user_id=payload.user_id,
            settings=settings,
        )

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return

        settings = await self.store.get_guild_settings(message.guild.id, message.guild.name)
        referenced = await self._resolve_referenced_message(message)

        if await self._is_admin_tax_reply_trigger(message, settings):
            if isinstance(referenced, discord.Message) and isinstance(message.channel, discord.TextChannel):
                created = await self._try_create_tax_case(
                    guild=message.guild,
                    source_channel=message.channel,
                    target_message=referenced,
                    triggered_by_user_id=message.author.id,
                    settings=settings,
                )
                if created:
                    await message.reply("已按管理员指令触发收税。", mention_author=False)

        if settings.tax_channel_id and message.channel.id == settings.tax_channel_id:
            image_count = self._count_images(message)
            if image_count > 0:
                outcome = await self.store.submit_tax_images(message.guild.id, message.author.id, image_count)
                settled = outcome["settled"]
                if settled:
                    await message.reply(
                        f"补税完成，已结清 {len(settled)} 单。继续保持别发太屎。",
                        mention_author=False,
                    )
                elif outcome["updated"]:
                    latest = outcome["updated"][0]
                    remain = max(latest.required_images - latest.submitted_images, 0)
                    await message.reply(
                        f"已收到 {image_count} 张图，还差 {remain} 张。",
                        mention_author=False,
                    )

        if settings.ai_enabled and await self._is_direct_ai_trigger(message):
            prompt = self._extract_direct_ai_prompt(message)
            image_urls = self._extract_image_urls_from_message(message)
            if not prompt and not image_urls:
                await message.reply("艾特我之后顺手说一句想聊什么。", mention_author=False)
                return

            global_settings = await self.store.get_global_settings()
            if await self._handle_direct_bot_command(
                message,
                prompt=prompt,
                referenced=referenced,
                guild_settings=settings,
                global_settings=global_settings,
            ):
                return

            messages = [
                {
                    "role": "system",
                    "content": self._compose_ai_system_prompt(
                        self._resolve_system_prompt(global_settings),
                        global_settings,
                    ),
                }
            ]
            messages.extend(await self._build_reference_context_messages(message, referenced))
            messages.append(
                {
                    "role": "user",
                    "content": self._build_user_multimodal_content(
                        f"{message.author.display_name}: {prompt}",
                        image_urls,
                        empty_text_fallback=f"{message.author.display_name}: 请结合图片内容回复。",
                    ),
                }
            )

            try:
                reply = await self.openrouter.chat(
                    messages,
                    profile=global_settings.chat_model_profile,
                    fallback_profiles=global_settings.chat_fallback_profiles,
                )
            except Exception as exc:  # pragma: no cover - network bound
                await message.reply(f"AI 调用失败：{self._describe_error(exc)}", mention_author=False)
                return

            await self.store.increment_user_stat(message.guild.id, message.author.id, "ai_calls")
            await self._reply_in_chunks(message, reply)
            return

        await self.process_commands(message)

    @tasks.loop(minutes=1)
    async def tax_deadline_watcher(self) -> None:
        expired_cases = await self.store.expire_due_tax_cases()
        for tax_case in expired_cases:
            guild = self.get_guild(tax_case.guild_id)
            if guild is None:
                continue
            settings = await self.store.get_guild_settings(guild.id, guild.name)
            member = guild.get_member(tax_case.user_id)
            if member is None:
                continue

            reason = "搬屎交税逾期未缴"
            try:
                await member.timeout(
                    utcnow() + timedelta(hours=settings.mute_hours),
                    reason=reason,
                )
            except discord.HTTPException:
                LOGGER.warning("Failed to timeout member %s in guild %s", member.id, guild.id)

            target_channel = guild.get_channel(settings.log_channel_id or tax_case.trigger_channel_id)
            if isinstance(target_channel, discord.TextChannel):
                await target_channel.send(
                    f"{member.mention} 未按时补税，已禁言 {settings.mute_hours} 小时。"
                )

    @tax_deadline_watcher.before_loop
    async def before_tax_deadline_watcher(self) -> None:
        await self.wait_until_ready()

    async def _announce_tax_case(
        self,
        guild: discord.Guild,
        source_channel: discord.TextChannel,
        offender: discord.Member | discord.User,
        settings: GuildSettings,
    ) -> None:
        tax_channel = guild.get_channel(settings.tax_channel_id) if settings.tax_channel_id else None
        tax_channel_text = tax_channel.mention if isinstance(tax_channel, discord.TextChannel) else "税务频道"
        warning = settings.warn_text.format(
            user_mention=offender.mention,
            tax_channel=tax_channel_text,
            minutes=settings.tax_payment_window_minutes,
            required_images=settings.tax_required_images,
            mute_hours=settings.mute_hours,
        )
        await source_channel.send(warning)
        if isinstance(tax_channel, discord.TextChannel):
            await tax_channel.send(
                f"{offender.mention} 新增一笔屎税，请发 {settings.tax_required_images} 张图完成补税。"
            )

    async def _try_create_tax_case(
        self,
        *,
        guild: discord.Guild,
        source_channel: discord.TextChannel,
        target_message: discord.Message,
        triggered_by_user_id: int,
        settings: GuildSettings,
    ) -> bool:
        if target_message.author.bot or target_message.author.id == triggered_by_user_id:
            return False
        if not self._message_has_image(target_message):
            return False

        existing = await self.store.get_tax_case_for_message(guild.id, target_message.id)
        if existing is not None:
            return False

        tax_case = TaxCase(
            case_id=uuid.uuid4().hex[:10],
            guild_id=guild.id,
            user_id=target_message.author.id,
            trigger_channel_id=source_channel.id,
            message_id=target_message.id,
            triggered_by_user_id=triggered_by_user_id,
            required_images=settings.tax_required_images,
            deadline_at=utcnow() + timedelta(minutes=settings.tax_payment_window_minutes),
        )
        await self.store.add_tax_case(tax_case)
        await self._announce_tax_case(guild, source_channel, target_message.author, settings)
        return True

    async def _is_admin_tax_reply_trigger(self, message: discord.Message, settings: GuildSettings) -> bool:
        if not settings.tax_enabled:
            return False
        if not message.reference:
            return False
        if not message.author.guild_permissions.manage_guild:
            return False
        normalized = re.sub(r"\s+", "", (message.content or "").strip())
        return normalized in TAX_REPLY_KEYWORDS or normalized.startswith("税")

    @staticmethod
    def _message_has_image(message: discord.Message) -> bool:
        return EntertainmentBot._count_images(message) > 0

    @staticmethod
    def _count_images(message: discord.Message) -> int:
        attachment_count = sum(
            1
            for attachment in message.attachments
            if EntertainmentBot._attachment_is_image(attachment)
        )
        url_count = len(IMAGE_URL_RE.findall(message.content or ""))
        return attachment_count + url_count

    @staticmethod
    def _attachment_is_image(attachment: discord.Attachment) -> bool:
        if (attachment.content_type or "").startswith("image/"):
            return True
        filename = (attachment.filename or "").lower()
        return filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))

    @staticmethod
    def _is_shit_emoji(configured: str, emoji: discord.PartialEmoji) -> bool:
        expected_values = {
            item.strip().lower()
            for item in configured.split(",")
            if item.strip()
        }
        if not expected_values:
            return False
        emoji_name = (emoji.name or "").strip().lower()
        emoji_id = str(emoji.id) if emoji.id is not None else ""
        emoji_rendered = str(emoji).strip().lower()

        candidates = {
            emoji_name,
            emoji_id,
            emoji_rendered,
            emoji_rendered.strip(":"),
        }
        for expected in expected_values | SHIT_EMOJI_ALIASES:
            if expected in candidates:
                return True
            if expected.startswith(":") and expected.endswith(":") and expected.strip(":") in candidates:
                return True
        return "💩" in candidates and bool(expected_values & SHIT_EMOJI_ALIASES)

    async def _is_direct_ai_trigger(self, message: discord.Message) -> bool:
        if self.user is None:
            return False
        if self.user in message.mentions:
            return True
        referenced = await self._resolve_referenced_message(message)
        return isinstance(referenced, discord.Message) and referenced.author.id == self.user.id

    def _extract_direct_ai_prompt(self, message: discord.Message) -> str:
        if self.user is None:
            return message.content.strip()
        content = message.content
        content = content.replace(f"<@{self.user.id}>", "")
        content = content.replace(f"<@!{self.user.id}>", "")
        return content.strip()

    @staticmethod
    def _build_user_multimodal_content(
        prompt: str,
        image_urls: list[str],
        *,
        empty_text_fallback: str,
    ) -> str | list[dict[str, object]]:
        cleaned_prompt = prompt.strip()
        if not image_urls:
            return cleaned_prompt

        content: list[dict[str, object]] = [
            {"type": "text", "text": cleaned_prompt or empty_text_fallback}
        ]
        for image_url in image_urls:
            content.append({"type": "image_url", "image_url": {"url": image_url}})
        return content

    @staticmethod
    def _extract_image_urls_from_message(message: discord.Message) -> list[str]:
        urls: list[str] = []
        for attachment in message.attachments:
            if EntertainmentBot._attachment_is_image(attachment):
                urls.append(attachment.url)
        urls.extend(IMAGE_URL_RE.findall(message.content or ""))
        for embed in message.embeds:
            if embed.image and embed.image.url:
                urls.append(embed.image.url)
            if embed.thumbnail and embed.thumbnail.url:
                urls.append(embed.thumbnail.url)
        return urls

    async def _build_reference_context_messages(
        self,
        message: discord.Message,
        referenced: discord.Message | None,
    ) -> list[dict[str, str | list[dict[str, object]]]]:
        if referenced is None:
            return []
        if self.user is not None and referenced.author.id == self.user.id:
            assistant_text = referenced.content.strip() or "[上一条 AI 回复无文字]"
            return [{"role": "assistant", "content": assistant_text}]

        referenced_text = referenced.content.strip()
        referenced_images = self._extract_image_urls_from_message(referenced)
        if not referenced_text and not referenced_images:
            return []
        content = self._build_user_multimodal_content(
            f"你正在回复这条消息，先理解它再回答：{referenced.author.display_name}: {referenced_text}",
            referenced_images,
            empty_text_fallback=f"你正在回复 {referenced.author.display_name} 发来的图片，请结合图片内容回答。",
        )
        return [{"role": "user", "content": content}]

    @staticmethod
    def _normalize_image_style(style: str | None) -> str | None:
        lowered = (style or "").strip().lower()
        if lowered in {"safe", "pretty", "sfw", "美图"}:
            return "safe"
        if lowered in {"explicit", "lewd", "nsfw", "涩图", "色图"}:
            return "explicit"
        return None

    @staticmethod
    def _merge_image_tags(*parts: str) -> str:
        merged = " ".join(part.strip() for part in parts if part and part.strip())
        cleaned = RATING_TAG_RE.sub("", merged)
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _legacy_image_tags(guild_settings: GuildSettings) -> str:
        return re.sub(r"\s+", " ", RATING_TAG_RE.sub("", guild_settings.danbooru_default_tags)).strip()

    async def _resolve_effective_image_preferences(
        self,
        guild_id: int,
        user_id: int,
        guild_settings: GuildSettings,
    ) -> tuple[UserImagePreferences, str, str]:
        preferences = await self.store.get_user_preferences(guild_id, user_id)
        safe_profile = preferences.safe_image_site_profile or guild_settings.safe_image_site_profile or "danbooru"
        explicit_profile = preferences.explicit_image_site_profile or guild_settings.explicit_image_site_profile or "danbooru"
        return preferences, safe_profile, explicit_profile

    async def _fetch_image_post(
        self,
        *,
        guild_settings: GuildSettings,
        guild_id: int,
        user_id: int,
        rating_mode: str,
        extra_tags: str,
        profile_override: str | None = None,
    ) -> dict[str, object]:
        preferences, safe_profile, explicit_profile = await self._resolve_effective_image_preferences(
            guild_id,
            user_id,
            guild_settings,
        )
        profile = profile_override or (safe_profile if rating_mode == "safe" else explicit_profile)
        base_tags = (
            preferences.safe_image_tags or guild_settings.safe_image_default_tags or self._legacy_image_tags(guild_settings)
            if rating_mode == "safe"
            else preferences.explicit_image_tags or guild_settings.explicit_image_default_tags or self._legacy_image_tags(guild_settings)
        )
        return await self.image_sources.random_post(
            profile=profile,
            rating_mode=rating_mode,
            base_tags=base_tags,
            extra_tags=extra_tags,
        )

    async def _build_image_response_embed(
        self,
        *,
        guild_settings: GuildSettings,
        guild_id: int,
        user_id: int,
        rating_mode: str,
        extra_tags: str,
        profile_override: str | None = None,
    ) -> discord.Embed:
        post = await self._fetch_image_post(
            guild_settings=guild_settings,
            guild_id=guild_id,
            user_id=user_id,
            rating_mode=rating_mode,
            extra_tags=extra_tags,
            profile_override=profile_override,
        )
        return self._build_image_embed(post)

    async def _handle_direct_bot_command(
        self,
        message: discord.Message,
        *,
        prompt: str,
        referenced: discord.Message | None,
        guild_settings: GuildSettings,
        global_settings,
    ) -> bool:
        normalized = self._normalize_direct_prompt(prompt)

        if draw_request := self._parse_direct_draw_request(prompt):
            await self._handle_direct_draw(
                message,
                draw_request,
                referenced=referenced,
                global_settings=global_settings,
            )
            return True

        explicit_tags = self._extract_direct_image_tags(prompt, EXPLICIT_IMAGE_KEYWORDS)
        if explicit_tags is not None:
            await self._handle_direct_image_request(
                message,
                guild_settings=guild_settings,
                rating_mode="explicit",
                extra_tags=explicit_tags,
                nsfw_required=True,
            )
            return True

        safe_tags = self._extract_direct_image_tags(prompt, SAFE_IMAGE_KEYWORDS)
        if safe_tags is not None:
            await self._handle_direct_image_request(
                message,
                guild_settings=guild_settings,
                rating_mode="safe",
                extra_tags=safe_tags,
                nsfw_required=False,
            )
            return True

        if self._is_direct_sauce_request(prompt):
            await self._handle_direct_saucenao(message, referenced=referenced)
            return True

        if any(keyword in normalized for keyword in ("今日运势", "运势")):
            result = FunService.daily_fortune(
                message.author.id,
                message.guild.id,
                config=self._get_fun_payload(global_settings),
            )
            await self.store.increment_user_stat(message.guild.id, message.author.id, "fortune_calls")
            await message.reply(
                f"{message.author.mention} 今日运势 `{result['score']}/100`\n{result['text']}",
                mention_author=False,
            )
            return True

        if any(keyword in normalized for keyword in ("轮盘", "roulette")):
            result = FunService.roulette(config=self._get_fun_payload(global_settings))
            await self.store.increment_user_stat(message.guild.id, message.author.id, "roulette_calls")
            await message.reply(
                f"{message.author.mention} 扣下扳机……\n{result['text']} (弹仓位置: {result['chamber']}/6)",
                mention_author=False,
            )
            return True

        if any(keyword in normalized for keyword in ("抛硬币", "硬币", "coin")):
            result = FunService.coinflip(
                message.author.id,
                message.guild.id,
                config=self._get_fun_payload(global_settings),
            )
            await message.reply(
                f"{message.author.mention} {result['text']}\n结果：`{result['side']}`",
                mention_author=False,
            )
            return True

        if any(keyword in normalized for keyword in ("抽签", "签运")):
            result = FunService.lottery(
                message.author.id,
                message.guild.id,
                config=self._get_fun_payload(global_settings),
            )
            await self.store.increment_user_stat(message.guild.id, message.author.id, "lottery_calls")
            await message.reply(
                f"{message.author.mention} 今日签运点数：`{result['roll']}`\n"
                f"稀有度：`{result['rarity']}`\n{result['text']}\n{result['omen']}",
                mention_author=False,
            )
            return True

        if any(keyword in normalized for keyword in ("老婆", "老公", "waifu")):
            members = [member for member in message.guild.members if not member.bot]
            target_id = FunService.pick_waifu(
                [member.id for member in members],
                message.guild.id,
                message.author.id,
                utcnow().strftime("%Y-%m-%d"),
            )
            if target_id is None:
                await message.reply("服务器里没有可选成员。", mention_author=False)
                return True
            target = message.guild.get_member(target_id)
            await message.reply(
                f"{message.author.mention} 今日命中目标：{target.mention if target else target_id}",
                mention_author=False,
            )
            return True

        if diagnosis_target := self._parse_direct_suffix_command(prompt, "诊断"):
            result = FunService.diagnose(
                diagnosis_target,
                message.guild.id,
                message.author.id,
                config=self._get_fun_payload(global_settings),
            )
            await message.reply(
                f"`{diagnosis_target}` 的稳定性诊断：`{result['score']}/100`\n"
                f"结论：`{result['label']}`\n{result['note']}",
                mention_author=False,
            )
            return True

        if rate_target := self._parse_direct_suffix_command(prompt, "评分"):
            result = FunService.rate(
                rate_target,
                message.guild.id,
                message.author.id,
                config=self._get_fun_payload(global_settings),
            )
            await message.reply(
                f"`{rate_target}` 的评分：`{result['score']}/100`\n"
                f"等级：`{result['label']}`\n{result['note']}",
                mention_author=False,
            )
            return True

        if choose_options := self._parse_direct_choose_options(prompt):
            try:
                result = FunService.choose(
                    choose_options,
                    message.guild.id,
                    message.author.id,
                    config=self._get_fun_payload(global_settings),
                )
            except ValueError as exc:
                await message.reply(str(exc), mention_author=False)
                return True
            await message.reply(
                f"{message.author.mention} 我替你做了决定：`{result['choice']}`",
                mention_author=False,
            )
            return True

        if self._is_direct_eightball(prompt):
            result = FunService.eight_ball(
                prompt,
                message.guild.id,
                message.author.id,
                config=self._get_fun_payload(global_settings),
            )
            await message.reply(
                f"{message.author.mention} 回答：{result['answer']}",
                mention_author=False,
            )
            return True

        return False

    async def _handle_direct_draw(
        self,
        message: discord.Message,
        draw_request: dict[str, str | None],
        *,
        referenced: discord.Message | None,
        global_settings,
    ) -> None:
        urls = self._extract_image_urls_from_message(message)
        if referenced is not None:
            for image_url in self._extract_image_urls_from_message(referenced):
                if image_url not in urls:
                    urls.append(image_url)

        prompt_text = (draw_request.get("prompt") or "").strip()
        if not prompt_text and urls:
            prompt_text = "请基于提供的图片做一次高质量改图，保留主体和关键细节。"
        if not prompt_text:
            await message.reply("想让我画图的话，至少给一句描述，或者带上一张参考图。", mention_author=False)
            return

        try:
            result = await self.openrouter.draw(
                prompt=prompt_text,
                profile=getattr(global_settings, "draw_model_profile", "legacy-draw"),
                fallback_profiles=getattr(global_settings, "draw_fallback_profiles", ""),
                size="1:1",
                variants=1,
                urls=urls or None,
            )
            resolved = await self._await_draw_completion(result)
        except Exception as exc:
            await message.reply(f"绘图失败：{self._describe_error(exc)}", mention_author=False)
            return

        images = self._extract_draw_result_urls(resolved)
        if not images:
            await message.reply(f"绘图任务回来了，但没吐出图片地址：{resolved}", mention_author=False)
            return

        header_parts = [f"档案: `{resolved.get('_profile', getattr(global_settings, 'draw_model_profile', 'legacy-draw'))}`"]
        if resolved.get("_warning"):
            header_parts.append(str(resolved["_warning"]))
        await self._reply_in_chunks(message, "\n".join([" | ".join(header_parts), *images]))

    async def _handle_direct_image_request(
        self,
        message: discord.Message,
        *,
        guild_settings: GuildSettings,
        rating_mode: str,
        extra_tags: str,
        nsfw_required: bool,
    ) -> None:
        if nsfw_required and not self._channel_is_nsfw(message.channel):
            await message.reply("涩图去 NSFW 频道叫我。", mention_author=False)
            return

        try:
            post = await self._fetch_image_post(
                guild_settings=guild_settings,
                guild_id=message.guild.id,
                user_id=message.author.id,
                rating_mode=rating_mode,
                extra_tags=extra_tags,
            )
        except Exception as exc:
            await message.reply(f"图站请求失败：{self._describe_error(exc)}", mention_author=False)
            return

        await self.store.increment_user_stat(message.guild.id, message.author.id, "danbooru_calls")
        await message.reply(embed=self._build_image_embed(post), mention_author=False)

    @staticmethod
    def _build_image_embed(post: dict[str, object]) -> discord.Embed:
        site_label = str(post.get("site_label") or post.get("site") or "Image")
        embed = discord.Embed(
            title=f"{site_label} #{post['id']}",
            description=f"rating: `{post['rating']}`\n[查看原帖]({post['post_url']})",
            color=discord.Color.blurple(),
        )
        if post.get("file_url"):
            embed.set_image(url=str(post["file_url"]))
        tags_text = str(post.get("tags") or "无标签")[:900]
        embed.add_field(name="Tags", value=tags_text, inline=False)
        return embed

    async def _handle_direct_saucenao(
        self,
        message: discord.Message,
        *,
        referenced: discord.Message | None,
    ) -> None:
        image_urls = self._extract_image_urls_from_message(message)
        if referenced is not None:
            for image_url in self._extract_image_urls_from_message(referenced):
                if image_url not in image_urls:
                    image_urls.append(image_url)
        if not image_urls:
            await message.reply("你要我搜图，总得给我一张图。可以直接带图，或者回复一条带图消息。", mention_author=False)
            return

        try:
            payload = await self.saucenao.search(image_urls[0])
        except Exception as exc:
            await message.reply(f"SauceNAO 搜图失败：{self._describe_error(exc)}", mention_author=False)
            return
        await message.reply(embed=self._build_saucenao_embed(payload, image_urls[0]), mention_author=False)

    @staticmethod
    def _build_saucenao_embed(payload: dict[str, object], image_url: str) -> discord.Embed:
        header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
        results = payload.get("results") if isinstance(payload.get("results"), list) else []
        embed = discord.Embed(
            title="SauceNAO 反查结果",
            description=f"原图: [点击查看]({image_url})",
            color=discord.Color.orange(),
        )
        if results:
            top = results[0] if isinstance(results[0], dict) else {}
            top_header = top.get("header") if isinstance(top.get("header"), dict) else {}
            top_data = top.get("data") if isinstance(top.get("data"), dict) else {}
            similarity = top_header.get("similarity", "?")
            title = (
                top_data.get("title")
                or top_data.get("eng_name")
                or top_data.get("source")
                or top_data.get("creator")
                or "未命名结果"
            )
            index_name = top_header.get("index_name", "未知索引")
            ext_urls = [str(item) for item in top_data.get("ext_urls", []) if isinstance(item, str)]
            if top_header.get("thumbnail"):
                embed.set_thumbnail(url=str(top_header["thumbnail"]))
            embed.add_field(
                name="最佳匹配",
                value=f"`{title}`\n相似度: `{similarity}%`\n来源库: `{index_name}`",
                inline=False,
            )
            if ext_urls:
                embed.add_field(name="外链", value="\n".join(ext_urls[:3]), inline=False)

        short_results = []
        for item in results[:5]:
            if not isinstance(item, dict):
                continue
            item_header = item.get("header") if isinstance(item.get("header"), dict) else {}
            item_data = item.get("data") if isinstance(item.get("data"), dict) else {}
            similarity = item_header.get("similarity", "?")
            title = (
                item_data.get("title")
                or item_data.get("eng_name")
                or item_data.get("source")
                or item_data.get("creator")
                or "未命名结果"
            )
            short_results.append(f"{similarity}% | {title}")
        if short_results:
            embed.add_field(name="候选结果", value="\n".join(short_results), inline=False)

        status = header.get("status")
        if status is not None:
            embed.set_footer(text=f"status={status}")
        return embed

    @staticmethod
    def _normalize_direct_prompt(prompt: str) -> str:
        return re.sub(r"\s+", "", (prompt or "").strip()).lower()

    @staticmethod
    def _extract_direct_image_tags(prompt: str, keywords: tuple[str, ...]) -> str | None:
        trimmed = (prompt or "").strip()
        normalized = re.sub(r"\s+", "", trimmed)
        for keyword in keywords:
            if normalized.startswith(keyword):
                raw = trimmed
                if raw.startswith(keyword):
                    return raw[len(keyword):].strip(" ：:-")
                return ""
        return None

    @staticmethod
    def _parse_direct_draw_request(prompt: str) -> dict[str, str | None] | None:
        trimmed = (prompt or "").strip()
        lowered = trimmed.lower()
        for prefix in DIRECT_DRAW_PREFIXES:
            if lowered.startswith(prefix):
                remainder = trimmed[len(prefix):].strip(" ：:-")
                return {"prompt": remainder or None}
        return None

    @staticmethod
    def _is_direct_sauce_request(prompt: str) -> bool:
        trimmed = (prompt or "").strip().lower()
        return trimmed.startswith("搜图") or trimmed.startswith("sauce") or trimmed.startswith("source")

    @staticmethod
    def _parse_direct_choose_options(prompt: str) -> list[str] | None:
        trimmed = (prompt or "").strip()
        lowered = trimmed.lower()
        if lowered.startswith("choose"):
            body = trimmed[6:].strip(" ：:-")
            return [item.strip() for item in body.split("|") if item.strip()]
        if trimmed.startswith("选一个"):
            body = trimmed[3:].strip(" ：:-")
            return [item.strip() for item in body.split("|") if item.strip()]
        return None

    @staticmethod
    def _is_direct_eightball(prompt: str) -> bool:
        trimmed = (prompt or "").strip()
        lowered = trimmed.lower()
        return lowered.startswith("8ball") or lowered.startswith("eightball")

    @staticmethod
    def _parse_direct_suffix_command(prompt: str, prefix: str) -> str | None:
        trimmed = (prompt or "").strip()
        if not trimmed.startswith(prefix):
            return None
        body = trimmed[len(prefix):].strip(" ：:-")
        return body or None

    @staticmethod
    def _channel_is_nsfw(channel: discord.abc.GuildChannel | discord.Thread | None) -> bool:
        if channel is None:
            return False
        if hasattr(channel, "is_nsfw"):
            try:
                return bool(channel.is_nsfw())
            except TypeError:
                pass
        parent = getattr(channel, "parent", None)
        if parent is not None and hasattr(parent, "is_nsfw"):
            return bool(parent.is_nsfw())
        return False

    async def _await_draw_completion(self, initial_result: dict[str, object]) -> dict[str, object]:
        if not isinstance(initial_result, dict):
            raise RuntimeError(f"Unexpected draw response: {initial_result!r}")

        data = initial_result.get("data") if isinstance(initial_result.get("data"), dict) else initial_result
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected draw response data: {initial_result}")

        profile = str(initial_result.get("_profile", "") or "")
        provider = str(initial_result.get("_provider", "") or "")
        warning = initial_result.get("_warning")

        status = str(data.get("status", "")).lower()
        if status in {"succeeded", "failed"}:
            if provider:
                data["_provider"] = provider
            if profile:
                data["_profile"] = profile
            if warning:
                data["_warning"] = warning
            return data

        task_id = str(data.get("id", "") or "")
        if not task_id:
            return data

        for _ in range(24):
            await asyncio.sleep(2.5)
            polled = await self.openrouter.draw_result(task_id, profile=profile or None, provider=provider or None)
            polled_data = polled.get("data") if isinstance(polled, dict) and isinstance(polled.get("data"), dict) else polled
            if not isinstance(polled_data, dict):
                continue
            if provider:
                polled_data["_provider"] = provider
            if profile:
                polled_data["_profile"] = profile
            if warning:
                polled_data["_warning"] = warning
            polled_status = str(polled_data.get("status", "")).lower()
            if polled_status in {"succeeded", "failed"}:
                return polled_data
        return data

    @staticmethod
    def _extract_draw_result_urls(result: dict[str, object]) -> list[str]:
        urls: list[str] = []
        results = result.get("results") if isinstance(result, dict) else None
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict) and isinstance(item.get("url"), str):
                    urls.append(item["url"])
        if not urls and isinstance(result.get("url"), str):
            urls.append(result["url"])
        return urls

    @staticmethod
    def _split_text_chunks(text: str, limit: int = 1800) -> list[str]:
        text = (text or "").strip()
        if not text:
            return ["嗯？这次模型什么都没吐出来。"]
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        current = ""
        for paragraph in text.splitlines():
            piece = paragraph if not current else f"\n{paragraph}"
            if len(current) + len(piece) <= limit:
                current += piece
                continue
            if current:
                chunks.append(current)
            current = paragraph
            while len(current) > limit:
                chunks.append(current[:limit])
                current = current[limit:]
        if current:
            chunks.append(current)
        return chunks

    async def _send_followup_chunks(self, interaction: discord.Interaction, text: str) -> None:
        chunks = self._split_text_chunks(text)
        for chunk in chunks:
            await interaction.followup.send(chunk)

    async def _reply_in_chunks(self, message: discord.Message, text: str) -> None:
        chunks = self._split_text_chunks(text)
        first = True
        for chunk in chunks:
            if first:
                await message.reply(chunk, mention_author=False)
                first = False
            else:
                await message.channel.send(chunk)

    @staticmethod
    def _describe_error(exc: Exception) -> str:
        text = str(exc).strip()
        return text or exc.__class__.__name__


class BotManager:
    def __init__(self, bot: EntertainmentBot, env: EnvSettings) -> None:
        self.bot = bot
        self.env = env
        self._task: asyncio.Task | None = None
        self._last_error: str | None = None

    async def _run_bot(self) -> None:
        try:
            await self.bot.start(self.env.discord_token)
        except Exception as exc:  # pragma: no cover - network/runtime bound
            self._last_error = f"{type(exc).__name__}: {exc}"
            LOGGER.exception("Discord bot failed to start or crashed")
            raise

    async def start(self) -> None:
        if not self.env.discord_token or self._task is not None:
            return
        self._last_error = None
        self._task = asyncio.create_task(self._run_bot())

    async def stop(self) -> None:
        if self._task is None:
            return
        await self.bot.close()
        try:
            await self._task
        except Exception:  # pragma: no cover - shutdown path
            LOGGER.exception("Bot task closed with error")
        self._task = None

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_error(self) -> str | None:
        return self._last_error
