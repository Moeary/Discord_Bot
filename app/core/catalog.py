from __future__ import annotations

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
}


GUILD_SETTING_SPECS = {
    "ai_enabled": {"type": "bool", "description": "是否启用 AI 功能。"},
    "fun_enabled": {"type": "bool", "description": "是否启用娱乐功能。"},
    "tax_enabled": {"type": "bool", "description": "是否启用搬屎交税。"},
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
        "description": "调用当前聊天档案与人设聊天，支持可选图片输入。",
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
        "group": "ai",
        "name": "/ai image",
        "description": "AI 绘图别名命令。",
        "permission": "user",
        "entrypoints": ["slash"],
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
        "name": "/fun roulette",
        "description": "进行一次毫无必要的轮盘实验。",
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
        "name": "/fun choose",
        "description": "让系统替你做一个懒惰但有效的选择。",
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
        "description": "抽取你今天的危险情感投射对象。",
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
        "name": "/fun lottery",
        "description": "领取今日签运和廉价命运解读。",
        "permission": "user",
        "entrypoints": ["slash", "@bot", "reply"],
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
        "name": "/fun diagnose",
        "description": "对某个对象做一次情绪稳定性诊断。",
        "permission": "user",
        "entrypoints": ["slash", "@bot", "reply"],
    },
    {
        "group": "fun",
        "name": "/fun rate",
        "description": "让系统对某个东西打分。",
        "permission": "user",
        "entrypoints": ["slash", "@bot", "reply"],
    },
    {
        "group": "fun",
        "name": "/fun duel",
        "description": "模拟两名测试对象之间的荒谬决斗。",
        "permission": "user",
        "entrypoints": ["slash"],
    },
    {
        "group": "config",
        "name": "/config view",
        "description": "查看当前配置，可选 scope: guild / global / all。",
        "permission": "admin",
        "entrypoints": ["slash"],
    },
    {
        "group": "config",
        "name": "/config global_view",
        "description": "兼容旧入口，等价于 /config view scope:global。",
        "permission": "admin",
        "entrypoints": ["slash"],
    },
    {
        "group": "config",
        "name": "/config set",
        "description": "修改配置，可选 scope: guild / global。",
        "permission": "admin",
        "entrypoints": ["slash"],
    },
    {
        "group": "config",
        "name": "/config global_set",
        "description": "兼容旧入口，等价于 /config set scope:global。",
        "permission": "admin",
        "entrypoints": ["slash"],
    },
    {
        "group": "config",
        "name": "/config tax_channel",
        "description": "直接指定税务频道。",
        "permission": "admin",
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
        return int(value)
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
        return int(value)
    return value


def get_setting_catalog() -> dict[str, object]:
    return {
        "global": deepcopy(GLOBAL_SETTING_SPECS),
        "guild": deepcopy(GUILD_SETTING_SPECS),
        "commands": deepcopy(COMMAND_REFERENCE),
    }
