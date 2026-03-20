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
    "system_prompt": {
        "type": "str",
        "description": "AI 对话的系统提示词。",
    },
    "summary_system_prompt": {
        "type": "str",
        "description": "AI 总结最近聊天时使用的系统提示词。",
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
    "warn_text": {
        "type": "str",
        "description": "搬屎交税警告模板，可用占位符见 README。",
    },
}


COMMAND_REFERENCE = [
    {
        "group": "ai",
        "name": "/ai chat",
        "description": "调用 OpenRouter 模型聊天，支持可选图片输入。",
    },
    {
        "group": "ai",
        "name": "/ai summary",
        "description": "总结当前频道最近的聊天记录。",
    },
    {
        "group": "ai",
        "name": "/ai draw",
        "description": "调用绘图接口生成图片。",
    },
    {
        "group": "ai",
        "name": "/ai image",
        "description": "AI 绘图别名命令。",
    },
    {
        "group": "fun",
        "name": "/fun danbooru",
        "description": "从 Danbooru 随机找图；NSFW 频道强制 rating:e，普通频道强制 rating:s。",
    },
    {
        "group": "fun",
        "name": "/fun pretty",
        "description": "快速来张安全美图。",
    },
    {
        "group": "fun",
        "name": "/fun lewd",
        "description": "快速来张涩图，仅限 NSFW 频道。",
    },
    {
        "group": "fun",
        "name": "/fun fortune",
        "description": "查看今日运势。",
    },
    {
        "group": "fun",
        "name": "/fun roulette",
        "description": "玩一局随机轮盘。",
    },
    {
        "group": "fun",
        "name": "/fun coin",
        "description": "抛硬币。",
    },
    {
        "group": "fun",
        "name": "/fun choose",
        "description": "从多个选项里随机挑一个。使用 | 分隔选项。",
    },
    {
        "group": "fun",
        "name": "/fun eightball",
        "description": "问机器人一个是非题。",
    },
    {
        "group": "fun",
        "name": "/fun waifu",
        "description": "随机抽取今日老婆/老公。",
    },
    {
        "group": "fun",
        "name": "/fun leaderboard",
        "description": "查看搬屎、AI、娱乐统计榜单。",
    },
    {
        "group": "fun",
        "name": "/fun lottery",
        "description": "每日抽签（升级版）。",
    },
    {
        "group": "fun",
        "name": "/fun ship",
        "description": "测一测两个人的同步率。",
    },
    {
        "group": "config",
        "name": "/config view",
        "description": "查看当前服务器配置。",
    },
    {
        "group": "config",
        "name": "/config global_view",
        "description": "查看全局 AI 档案和模型配置。",
    },
    {
        "group": "config",
        "name": "/config set",
        "description": "外部命令修改服务器设置。",
    },
    {
        "group": "config",
        "name": "/config global_set",
        "description": "外部命令修改全局 AI 档案设置。",
    },
    {
        "group": "config",
        "name": "/config tax_channel",
        "description": "直接指定税务频道。",
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
