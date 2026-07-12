from __future__ import annotations

import re
from copy import deepcopy


GLOBAL_SETTING_SPECS = {
    "chat_model_profile": {
        "type": "str",
        "description": "当前聊天模型档案名，对应 providers.json 里的 model_profiles。",
    },
    "chat_fallback_profiles": {
        "type": "str",
        "description": "聊天回退模型档案，逗号分隔多个档案名。",
    },
    "draw_model_profile": {
        "type": "str",
        "description": "当前绘图模型档案名，对应 providers.json 里的 model_profiles。",
    },
    "draw_fallback_profiles": {
        "type": "str",
        "description": "绘图回退模型档案，逗号分隔多个档案名。",
    },
    "persona_profile": {
        "type": "str",
        "description": "当前机器人人设档案名，对应 personas.json 里的 profile。",
    },
    "max_chat_history": {
        "type": "int",
        "description": "AI 对话带入上下文的最大消息条数。",
    },
    "ai_web_tools_enabled": {
        "type": "bool",
        "description": "AI 对话是否自动接入网页抓取与搜索上下文。",
    },
    "ai_web_fetch_enabled": {
        "type": "bool",
        "description": "AI 对话是否自动抓取用户消息里的网页 URL。",
    },
    "ai_web_search_enabled": {
        "type": "bool",
        "description": "AI 对话是否在用户明显要求查询实时/网络信息时自动搜索。",
    },
    "ai_web_fetch_limit": {
        "type": "int",
        "description": "单次 AI 对话最多自动抓取多少个网页 URL。",
    },
    "ai_web_search_result_limit": {
        "type": "int",
        "description": "单次 AI 对话最多带入多少条搜索结果。",
    },
    "ai_web_context_char_limit": {
        "type": "int",
        "description": "单次 AI 对话注入给模型的网页/搜索上下文总字符上限。",
    },
    "ai_web_fetch_max_bytes": {
        "type": "int",
        "description": "单个网页抓取时最多下载多少字节，避免长文档撑爆上下文和带宽。",
    },
    "ai_web_fetch_snippet_chars": {
        "type": "int",
        "description": "单个网页抓取后最多保留多少字符正文摘要。",
    },
}


GUILD_SETTING_SPECS = {
    "ai_enabled": {"type": "bool", "description": "是否启用 AI 功能。"},
    "fun_enabled": {"type": "bool", "description": "是否启用娱乐功能。"},
    "tax_enabled": {"type": "bool", "description": "是否启用搬屎交税。"},
    "minecraft_bridge_enabled": {"type": "bool", "description": "是否启用 Minecraft 与 Discord 双向聊天。"},
    "minecraft_server_id": {"type": "str", "description": "Paper 插件连接时使用的 server_id。"},
    "minecraft_server_address": {"type": "str", "description": "Minecraft 服务器地址，用于记录和展示，例如 127.0.0.1:30001。"},
    "minecraft_channel_id": {"type": "int_optional", "description": "Minecraft 聊天同步到的 Discord 频道 ID。"},
    "minecraft_token": {"type": "str", "description": "Paper 插件访问 FastAPI 的 Bearer/X-DC-Bot-Token。留空时只允许本机或内网连接。"},
    "minecraft_allow_no_token": {"type": "bool", "description": "未配置 token 时是否允许本机或内网地址直连。"},
    "minecraft_max_message_length": {"type": "int", "description": "Minecraft/Discord 互通单条消息最大长度。"},
    "welcome_channel_id": {"type": "int_optional", "description": "欢迎频道 ID，也支持直接传 `<#频道>`。"},
    "welcome_text": {
        "type": "str",
        "description": "欢迎文案，可用 `{user_mention}` 和 `{guild_name}` 占位。",
    },
    "verification_channel_id": {"type": "int_optional", "description": "答题领身份组的频道 ID，也支持 `<#频道>`。"},
    "verification_role_id": {"type": "int_optional", "description": "验证成功后发放的身份组 ID，也支持 `<@&身份组>`。"},
    "verification_question": {"type": "str", "description": "入群答题问题文本。"},
    "verification_answer": {"type": "str", "description": "入群答题正确答案。"},
    "verification_success_text": {
        "type": "str",
        "description": "验证成功提示，可用 `{user_mention}` 和 `{role_mention}`。",
    },
    "tax_channel_id": {"type": "int_optional", "description": "税务频道 ID。"},
    "log_channel_id": {"type": "int_optional", "description": "日志频道 ID。"},
    "shit_emoji": {
        "type": "str",
        "description": "用于触发搬屎交税的 emoji，支持逗号分隔多个别名，例如 shit,💩。",
    },
    "tax_required_images": {
        "type": "int",
        "description": "补税需要发送的图片数量。",
    },
    "tax_payment_window_minutes": {
        "type": "int",
        "description": "触发交税后允许补税的分钟数。",
    },
    "mute_hours": {"type": "int", "description": "逾期未交税时禁言小时数。"},
    "summary_limit": {
        "type": "int",
        "description": "AI 总结当前频道时最多读取多少条消息。",
    },
    "danbooru_default_tags": {
        "type": "str",
        "description": "Danbooru 默认搜索标签。",
    },
    "safe_image_site_profile": {
        "type": "str",
        "description": "本服务器默认的美图图站档案名，例如 danbooru。",
    },
    "explicit_image_site_profile": {
        "type": "str",
        "description": "本服务器默认的涩图图站档案名，例如 danbooru / rule34。",
    },
    "safe_image_default_tags": {
        "type": "str",
        "description": "本服务器默认的美图标签。",
    },
    "explicit_image_default_tags": {
        "type": "str",
        "description": "本服务器默认的涩图标签。",
    },
    "warn_text": {
        "type": "str",
        "description": "搬屎交税警告模板，可用占位符见 README。",
    },
}


COMMAND_REFERENCE = [
    {
        "group": "ai",
        "name": "/ai chat",
        "description": "调用当前聊天档案与人设聊天，支持可选图片输入，并按需自动抓网页/搜索。",
        "permission": "user",
        "entrypoints": ["slash", "@bot", "reply"],
    },
    {
        "group": "ai",
        "name": "/ai summary",
        "description": "总结当前频道最近的聊天记录。",
        "permission": "user",
        "entrypoints": ["slash"],
    },
    {
        "group": "ai",
        "name": "/ai draw",
        "description": "调用绘图接口生成图片或参考图改图。",
        "permission": "user",
        "entrypoints": ["slash", "@bot", "reply"],
    },
    {
        "group": "fun",
        "name": "/fun image",
        "description": "按图站档案抓一张图，可选美图或涩图模式。",
        "permission": "user",
        "entrypoints": ["slash", "@bot", "reply"],
    },
    {
        "group": "fun",
        "name": "/fun danbooru",
        "description": "固定从 Danbooru 抓图；NSFW 频道强制 rating:e，普通频道强制 rating:s。",
        "permission": "user",
        "entrypoints": ["slash"],
    },
    {
        "group": "fun",
        "name": "/fun rule34",
        "description": "固定从 Rule34 抓图，仅限 NSFW 频道。",
        "permission": "user",
        "entrypoints": ["slash"],
    },
    {
        "group": "fun",
        "name": "/fun image_prefs",
        "description": "查看你自己的图站默认来源和默认 tag。",
        "permission": "user",
        "entrypoints": ["slash"],
    },
    {
        "group": "fun",
        "name": "/fun image_source",
        "description": "设置你自己的美图或涩图默认图站档案。",
        "permission": "user",
        "entrypoints": ["slash"],
    },
    {
        "group": "fun",
        "name": "/fun image_tags",
        "description": "设置你自己的美图或涩图默认 tag。",
        "permission": "user",
        "entrypoints": ["slash"],
    },
    {
        "group": "fun",
        "name": "/fun image_sites",
        "description": "列出当前可用的图站档案。",
        "permission": "user",
        "entrypoints": ["slash"],
    },
    {
        "group": "fun",
        "name": "/fun sauce",
        "description": "用 SauceNAO 反查图片来源。",
        "permission": "user",
        "entrypoints": ["slash", "@bot", "reply", "message_menu"],
    },
    {
        "group": "fun",
        "name": "/fun pretty",
        "description": "快速来张安全美图。",
        "permission": "user",
        "entrypoints": ["slash", "@bot", "reply"],
    },
    {
        "group": "fun",
        "name": "/fun lewd",
        "description": "快速来张涩图，仅限 NSFW 频道。",
        "permission": "user",
        "entrypoints": ["slash", "@bot", "reply"],
    },
    {
        "group": "fun",
        "name": "/fun fortune",
        "description": "查看今日系统运势评估。",
        "permission": "user",
        "entrypoints": ["slash", "@bot", "reply"],
    },
    {
        "group": "fun",
        "name": "/fun coin",
        "description": "把选择权外包给一枚硬币。",
        "permission": "user",
        "entrypoints": ["slash", "@bot", "reply"],
    },
    {
        "group": "fun",
        "name": "/fun eightball",
        "description": "让系统对你的是非题做一次冷酷裁决。",
        "permission": "user",
        "entrypoints": ["slash", "@bot", "reply"],
    },
    {
        "group": "fun",
        "name": "/fun waifu",
        "description": "抽取你今天的 safe 二次元老婆图。",
        "permission": "user",
        "entrypoints": ["slash", "@bot", "reply"],
    },
    {
        "group": "fun",
        "name": "/fun leaderboard",
        "description": "查看本群娱乐与事故贡献排行榜。",
        "permission": "user",
        "entrypoints": ["slash"],
    },
    {
        "group": "fun",
        "name": "/fun ship",
        "description": "测量两名测试对象的电波同步率。",
        "permission": "user",
        "entrypoints": ["slash"],
    },
    {
        "group": "fun",
        "name": "/fun duel",
        "description": "模拟两名测试对象之间的荒谬决斗。",
        "permission": "user",
        "entrypoints": ["slash"],
    },
    {"group": "config", "name": "/config view", "description": "查看当前服务器和全局配置。", "permission": "admin", "entrypoints": ["slash"]},
    {"group": "config", "name": "/config set", "description": "按配置项名自动修改服务器或全局配置。", "permission": "admin", "entrypoints": ["slash"]},
    {
        "group": "minecraft",
        "name": "/minecraft bind",
        "description": "绑定自己的 Minecraft 用户名；Discord 转发到游戏时会用这个名字显示。",
        "permission": "user",
        "entrypoints": ["slash"],
    },
    {
        "group": "minecraft",
        "name": "/minecraft unbind",
        "description": "解除自己的 Minecraft 用户名绑定。",
        "permission": "user",
        "entrypoints": ["slash"],
    },
    {
        "group": "minecraft",
        "name": "/minecraft status",
        "description": "查看当前服务器的 Minecraft 互通配置和自己的绑定。",
        "permission": "user",
        "entrypoints": ["slash"],
    },
]


def cast_setting_value(specs: dict[str, dict[str, str]], key: str, value: object) -> object:
    if key not in specs:
        raise KeyError(f"Unknown setting key: {key}")

    value_type = specs[key]["type"]
    if value_type == "str":
        return str(value)
    if value_type == "int":
        return _parse_int_like(value)
    if value_type == "bool":
        if isinstance(value, bool):
            return value
        lowered = str(value).strip().lower()
        if lowered in {"1", "true", "yes", "on", "enable", "enabled"}:
            return True
        if lowered in {"0", "false", "no", "off", "disable", "disabled"}:
            return False
        raise ValueError(f"Cannot cast {value!r} to bool")
    if value_type == "int_optional":
        if value in {None, "", "none", "null", "off"}:
            return None
        return _parse_int_like(value)
    return value


def _parse_int_like(value: object) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    match = re.search(r"\d+", text)
    if not match:
        raise ValueError(f"Cannot cast {value!r} to int")
    return int(match.group(0))


def get_setting_catalog() -> dict[str, object]:
    return {
        "global": deepcopy(GLOBAL_SETTING_SPECS),
        "guild": deepcopy(GUILD_SETTING_SPECS),
        "commands": deepcopy(COMMAND_REFERENCE),
    }
