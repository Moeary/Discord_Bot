from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.core.catalog import GUILD_SETTING_SPECS, cast_setting_value
from app.core.config import EnvSettings
from app.models.state import GuildSettings, TaxCase, utcnow
from app.services.danbooru import DanbooruClient
from app.services.fun import FunService
from app.services.openrouter import OpenRouterClient
from app.services.state_store import StateStore


LOGGER = logging.getLogger(__name__)
IMAGE_URL_RE = re.compile(r"https?://\S+\.(?:png|jpe?g|gif|webp)", re.IGNORECASE)
RATING_TAG_RE = re.compile(r"\brating:(?:s|q|e|safe|questionable|explicit|general)\b", re.IGNORECASE)
TAX_REPLY_KEYWORDS = {"税", "交税", "补税", "税务"}
SHIT_EMOJI_ALIASES = {"shit", "poop", "pile_of_poo", "💩"}
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
        openrouter: OpenRouterClient,
        danbooru: DanbooruClient,
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
        self.danbooru = danbooru
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
        @app_commands.describe(prompt="你想让 AI 回复的内容", image="可选：附带一张图片给 AI 一起看")
        async def ai_chat(
            interaction: discord.Interaction,
            prompt: str,
            image: discord.Attachment | None = None,
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
                {"role": "system", "content": self._compose_ai_system_prompt(global_settings.system_prompt)},
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
                    model=global_settings.openrouter_model,
                )
            except Exception as exc:  # pragma: no cover - network bound
                await interaction.followup.send(f"AI 调用失败：{exc}")
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
                    self._compose_ai_system_prompt(global_settings.summary_system_prompt),
                    transcript,
                    model=global_settings.openrouter_model,
                )
            except Exception as exc:  # pragma: no cover - network bound
                await interaction.followup.send(f"AI 总结失败：{exc}")
                return

            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "ai_calls")
            await self._send_followup_chunks(interaction, reply)

        @ai_group.command(name="draw", description="AI 绘图")
        @app_commands.describe(
            prompt="你想生成的图片描述",
            model="可选：sora-image 或 gpt-image-1.5",
            size="可选：auto / 1:1 / 3:2 / 2:3",
            variants="可选：生成张数 1 或 2",
            image="可选：参考图",
        )
        async def ai_draw(
            interaction: discord.Interaction,
            prompt: str,
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
            draw_model = model or getattr(global_settings, "draw_model", "sora-image")
            urls: list[str] = []
            if image is not None and self._attachment_is_image(image):
                urls.append(image.url)

            try:
                result = await self.openrouter.draw(
                    prompt=prompt,
                    model=draw_model,
                    size=size,
                    variants=variants,
                    urls=urls,
                )
                resolved = await self._await_draw_completion(result)
            except Exception as exc:  # pragma: no cover - network bound
                await interaction.followup.send(f"绘图失败：{exc}")
                return

            images = self._extract_draw_result_urls(resolved)
            if not images:
                await interaction.followup.send(f"绘图任务已返回，但没有图片地址：{resolved}")
                return

            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "ai_calls")
            header = f"模型: `{draw_model}` | 比例: `{size}` | 数量: `{len(images)}`"
            await interaction.followup.send("\n".join([header, *images]))

        @fun_group.command(name="danbooru", description="Danbooru 随机找图")
        @app_commands.describe(tags="额外标签，例如 1girl blue_hair")
        async def fun_danbooru(interaction: discord.Interaction, tags: str | None = None) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            await interaction.response.defer(thinking=True)
            is_nsfw = self._channel_is_nsfw(interaction.channel)
            forced_rating = "rating:e" if is_nsfw else "rating:s"
            search_tags = self._compose_danbooru_tags(
                guild_settings.danbooru_default_tags,
                tags or "",
                forced_rating,
            )
            try:
                post = await self.danbooru.random_post(search_tags)
            except Exception as exc:  # pragma: no cover - network bound
                await interaction.followup.send(f"Danbooru 请求失败：{exc}")
                return

            embed = discord.Embed(
                title=f"Danbooru #{post['id']}",
                description=f"rating: `{post['rating']}`\n[查看原帖]({post['post_url']})",
                color=discord.Color.blurple(),
            )
            if post["file_url"]:
                embed.set_image(url=post["file_url"])
            tags_text = post["tags"][:900] if post["tags"] else "无标签"
            embed.add_field(name="Tags", value=tags_text, inline=False)
            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "danbooru_calls")
            await interaction.followup.send(embed=embed)

        @fun_group.command(name="fortune", description="看看今天运势")
        async def fun_fortune(interaction: discord.Interaction) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            result = FunService.daily_fortune(interaction.user.id, interaction.guild_id)
            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "fortune_calls")
            await interaction.response.send_message(
                f"{interaction.user.mention} 今日运势 `{result['score']}/100`\n{result['text']}"
            )

        @fun_group.command(name="roulette", description="玩一把轮盘")
        async def fun_roulette(interaction: discord.Interaction) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            result = FunService.roulette()
            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "roulette_calls")
            await interaction.response.send_message(
                f"{interaction.user.mention} 扣下扳机……\n{result['text']} (弹仓位置: {result['chamber']}/6)"
            )

        @fun_group.command(name="coin", description="抛个硬币")
        async def fun_coin(interaction: discord.Interaction) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            result = FunService.coinflip(interaction.user.id, interaction.guild_id)
            await interaction.response.send_message(
                f"{interaction.user.mention} {result['text']}\n结果：`{result['side']}`"
            )

        @fun_group.command(name="choose", description="从多个选项里替你选一个")
        @app_commands.describe(options="用 | 分隔多个选项，例如 火锅 | 烤肉 | 麻辣烫")
        async def fun_choose(interaction: discord.Interaction, options: str) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            try:
                result = FunService.choose(options.split("|"), interaction.guild_id, interaction.user.id)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return

            await interaction.response.send_message(
                f"{interaction.user.mention} 我替你做了决定：`{result['choice']}`"
            )

        @fun_group.command(name="eightball", description="问机器人一个是非题")
        @app_commands.describe(question="例如：我今天该不该熬夜？")
        async def fun_eightball(interaction: discord.Interaction, question: str) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            result = FunService.eight_ball(question, interaction.guild_id, interaction.user.id)
            await interaction.response.send_message(
                f"{interaction.user.mention} 问题：{question}\n回答：{result['answer']}"
            )

        @fun_group.command(name="waifu", description="抽今日老婆/老公")
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
                f"{interaction.user.mention} 今日命中目标：{target.mention if target else target_id}"
            )

        @fun_group.command(name="lottery", description="今日抽签（升级版）")
        async def fun_lottery(interaction: discord.Interaction) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            if not guild_settings.fun_enabled:
                await interaction.response.send_message("这个服务器没有开启娱乐功能。", ephemeral=True)
                return

            result = FunService.lottery(interaction.user.id, interaction.guild_id)
            await self.store.increment_user_stat(interaction.guild_id, interaction.user.id, "lottery_calls")
            await interaction.response.send_message(
                f"{interaction.user.mention} 今日签运点数：`{result['roll']}`\n"
                f"稀有度：`{result['rarity']}`\n{result['text']}\n{result['omen']}"
            )

        @fun_group.command(name="ship", description="测一测两个人的电波同步率")
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

            result = FunService.ship_score(
                member_a.id,
                member_b.id,
                interaction.guild_id,
                utcnow().strftime("%Y-%m-%d"),
            )
            await interaction.response.send_message(
                f"{member_a.mention} x {member_b.mention}\n"
                f"同步率：`{result['score']}%`\n{result['label']}"
            )

        @fun_group.command(name="leaderboard", description="看排行榜")
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

        @config_group.command(name="view", description="查看本服务器配置")
        async def config_view(interaction: discord.Interaction) -> None:
            guild_settings = await self._require_guild_settings(interaction)
            if guild_settings is None:
                return
            text = "\n".join(
                [
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
                ]
            )
            await interaction.response.send_message(text, ephemeral=True)

        @config_group.command(name="set", description="设置某个配置项")
        @app_commands.describe(key="配置项名", value="配置值")
        async def config_set(interaction: discord.Interaction, key: str, value: str) -> None:
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message("需要管理服务器权限。", ephemeral=True)
                return
            if key not in GUILD_SETTING_SPECS:
                await interaction.response.send_message(
                    f"未知配置项。可选：{', '.join(GUILD_SETTING_SPECS.keys())}",
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

        self.tree.add_command(ai_group)
        self.tree.add_command(fun_group)
        self.tree.add_command(config_group)

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

    @staticmethod
    def _compose_ai_system_prompt(base_prompt: str) -> str:
        return f"{base_prompt}\n{BOT_THINKING_GUARD}"

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
            messages = [
                {
                    "role": "system",
                    "content": self._compose_ai_system_prompt(global_settings.system_prompt),
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
                    model=global_settings.openrouter_model,
                )
            except Exception as exc:  # pragma: no cover - network bound
                await message.reply(f"AI 调用失败：{exc}", mention_author=False)
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
    def _compose_danbooru_tags(base_tags: str, extra_tags: str, forced_rating: str) -> str:
        merged = " ".join(part.strip() for part in [base_tags, extra_tags] if part.strip())
        cleaned = RATING_TAG_RE.sub("", merged)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return f"{forced_rating} {cleaned}".strip()

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

        status = str(data.get("status", "")).lower()
        if status in {"succeeded", "failed"}:
            return data

        task_id = str(data.get("id", "") or "")
        if not task_id:
            return data

        for _ in range(24):
            await asyncio.sleep(2.5)
            polled = await self.openrouter.draw_result(task_id)
            polled_data = polled.get("data") if isinstance(polled, dict) and isinstance(polled.get("data"), dict) else polled
            if not isinstance(polled_data, dict):
                continue
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
