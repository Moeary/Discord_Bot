from __future__ import annotations

import hashlib
from datetime import datetime


DEFAULT_FORTUNE_TEXT = [
    "大吉。今天你的大脑短暂地表现得像个合格组件。",
    "中吉。系统允许你谨慎地成功一次，别浪费。",
    "小吉。还能运转，但别误以为自己突然进化了。",
    "平。恭喜，你至少没有把局面进一步污染。",
    "小凶。冲动操作会把你送进事故报告附录。",
    "大凶。建议先闭嘴十秒，再决定要不要按发送。",
]

DEFAULT_EIGHT_BALL_TEXT = [
    "答案是肯定的。真遗憾，但事实如此。",
    "大概率可行。别用低级失误羞辱这份好运。",
    "可以试。出事了也请自行承担后果。",
    "先等等。你现在的判断力像泡水纸板。",
    "不太行。连宇宙都在劝你冷静。",
    "绝无可能。至少今天别做梦。",
]


DEFAULT_DUEL_FLAVORS = [
    "用语言学暴力取得了胜利。",
    "靠一点运气和一点不要脸赢下了回合。",
    "在对方反应过来之前完成了处决。",
    "以极其不体面的方式笑到了最后。",
    "让现场所有旁观者都陷入了复杂情绪。",
]


class FunService:
    @staticmethod
    def _list(config: dict[str, object] | None, key: str, fallback):
        if isinstance(config, dict) and isinstance(config.get(key), list):
            return config[key]
        return fallback

    @staticmethod
    def _text(config: dict[str, object] | None, key: str, fallback: str) -> str:
        if isinstance(config, dict) and isinstance(config.get(key), str) and str(config.get(key)).strip():
            return str(config.get(key))
        return fallback

    @staticmethod
    def _mapping(config: dict[str, object] | None, key: str, fallback: dict[str, str]) -> dict[str, str]:
        if isinstance(config, dict) and isinstance(config.get(key), dict):
            return {str(k): str(v) for k, v in dict(config[key]).items()}
        return fallback

    @staticmethod
    def daily_fortune(
        user_id: int,
        guild_id: int,
        now: datetime | None = None,
        config: dict[str, object] | None = None,
    ) -> dict[str, object]:
        now = now or datetime.utcnow()
        seed = f"{guild_id}:{user_id}:{now:%Y-%m-%d}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        fortune_text = FunService._list(config, "fortune_text", DEFAULT_FORTUNE_TEXT)
        score = int(digest[:8], 16) % 101
        index = min(len(fortune_text) - 1, ((100 - score) * len(fortune_text)) // 101)
        text = fortune_text[index]
        return {"score": score, "text": text}

    @staticmethod
    def coinflip(
        user_id: int,
        guild_id: int,
        now: datetime | None = None,
        config: dict[str, object] | None = None,
    ) -> dict[str, str]:
        now = now or datetime.utcnow()
        seed = f"coin:{guild_id}:{user_id}:{now:%Y-%m-%d:%H}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        head = int(digest[:2], 16) % 2 == 0
        return {
            "side": "正面" if head else "反面",
            "text": FunService._text(config, "coinflip_text", "宇宙替你掷了一次硬币。它对你的困境也没什么耐心。"),
        }

    @staticmethod
    def eight_ball(
        question: str,
        guild_id: int,
        user_id: int,
        now: datetime | None = None,
        config: dict[str, object] | None = None,
    ) -> dict[str, str]:
        now = now or datetime.utcnow()
        seed = f"8ball:{guild_id}:{user_id}:{now:%Y-%m-%d}:{question.strip()}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        answers = FunService._list(config, "eight_ball_text", DEFAULT_EIGHT_BALL_TEXT)
        index = int(digest[:8], 16) % len(answers)
        return {"answer": answers[index]}

    @staticmethod
    @staticmethod
    def duel(
        left_id: int,
        right_id: int,
        guild_id: int,
        day: str,
        config: dict[str, object] | None = None,
    ) -> dict[str, object]:
        pair = sorted([left_id, right_id])
        digest = hashlib.sha256(f"duel:{guild_id}:{day}:{pair[0]}:{pair[1]}".encode("utf-8")).hexdigest()
        winner = pair[int(digest[:2], 16) % 2]
        margin = int(digest[2:6], 16) % 101
        flavors = FunService._list(config, "duel_flavors", DEFAULT_DUEL_FLAVORS)
        flavor = flavors[int(digest[6:8], 16) % len(flavors)]
        return {"winner_id": winner, "margin": margin, "flavor": flavor}

    @staticmethod
    def ship_score(
        left_id: int,
        right_id: int,
        guild_id: int,
        day: str,
        config: dict[str, object] | None = None,
    ) -> dict[str, object]:
        pair = ":".join(str(value) for value in sorted([left_id, right_id]))
        digest = hashlib.sha256(f"ship:{guild_id}:{day}:{pair}".encode("utf-8")).hexdigest()
        score = int(digest[:8], 16) % 101
        labels = FunService._mapping(
            config,
            "ship_labels",
            {
                "reactor": "核反应堆级绑定",
                "hot": "高温暧昧",
                "ok": "能聊，但别急着交换戒指",
                "plastic": "塑料电波",
                "far": "建议保持社交距离",
            },
        )
        if score >= 90:
            label = labels["reactor"]
        elif score >= 70:
            label = labels["hot"]
        elif score >= 45:
            label = labels["ok"]
        elif score >= 20:
            label = labels["plastic"]
        else:
            label = labels["far"]
        return {"score": score, "label": label}
