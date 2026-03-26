from __future__ import annotations

import hashlib
import random
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


DEFAULT_LOTTERY_REWARDS = [
    (1, "传说级奖励：你今天发言有 5% 概率不被群友质疑。"),
    (6, "史诗级奖励：本日 Danbooru 首抽命中率得到轻微修正。"),
    (18, "稀有奖励：适合优雅整活，不适合大规模翻车。"),
    (35, "普通奖励：系统发放一份廉价心理安慰。"),
    (40, "安慰奖：至少生命体征还在。"),
]

DEFAULT_DIAGNOSIS_LABELS = [
    (15, "核心过热", "建议立刻停止发言，避免进一步丢脸。"),
    (35, "轻度失稳", "还能活动，但不建议做人生决策。"),
    (60, "勉强合格", "系统状态一般，足以应付低风险社交。"),
    (85, "运行良好", "令人意外，你今天看起来像是调过参。"),
    (101, "异常优秀", "这不科学，但我姑且记录为奇迹。"),
]

DEFAULT_RATE_LABELS = [
    (20, "灾难级", "它的存在本身就是一个错误日志。"),
    (45, "可疑", "理论上能用，实际上不建议。"),
    (70, "还行", "不耀眼，但至少没拖后腿。"),
    (90, "优良", "罕见地像是经过设计。"),
    (101, "杰作", "我本来想挑刺，但暂时失败了。"),
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
        score = int(digest[:8], 16) % 101
        fortune_text = FunService._list(config, "fortune_text", DEFAULT_FORTUNE_TEXT)
        text = fortune_text[min(score // 17, len(fortune_text) - 1)]
        return {"score": score, "text": text}

    @staticmethod
    def roulette(config: dict[str, object] | None = None) -> dict[str, object]:
        chamber = random.randint(1, 6)
        safe = chamber != 1
        return {
            "safe": safe,
            "chamber": chamber,
            "text": (
                FunService._text(config, "roulette_safe_text", "咔哒。系统暂时允许你继续污染聊天记录。")
                if safe
                else FunService._text(config, "roulette_fail_text", "砰。节目效果与生命教育同时达成。")
            ),
        }

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
    def choose(
        options: list[str],
        guild_id: int,
        user_id: int,
        now: datetime | None = None,
        config: dict[str, object] | None = None,
    ) -> dict[str, object]:
        cleaned = [option.strip() for option in options if option.strip()]
        if len(cleaned) < 2:
            raise ValueError(
                FunService._text(config, "choose_error", "至少给我两个选项。不然这不叫选择，只是你在公开场合自言自语。")
            )
        now = now or datetime.utcnow()
        seed = f"choose:{guild_id}:{user_id}:{now:%Y-%m-%d}:{'|'.join(cleaned)}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % len(cleaned)
        return {"choice": cleaned[index], "options": cleaned}

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
    def diagnose(
        target: str,
        guild_id: int,
        user_id: int,
        now: datetime | None = None,
        config: dict[str, object] | None = None,
    ) -> dict[str, object]:
        now = now or datetime.utcnow()
        seed = f"diagnose:{guild_id}:{user_id}:{now:%Y-%m-%d}:{target.strip()}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        score = int(digest[:8], 16) % 101
        labels = FunService._list(config, "diagnosis_labels", DEFAULT_DIAGNOSIS_LABELS)
        label, note = labels[-1][1], labels[-1][2]
        for upper, current_label, current_note in labels:
            if score < upper:
                label, note = current_label, current_note
                break
        return {"score": score, "label": label, "note": note}

    @staticmethod
    def rate(
        subject: str,
        guild_id: int,
        user_id: int,
        now: datetime | None = None,
        config: dict[str, object] | None = None,
    ) -> dict[str, object]:
        now = now or datetime.utcnow()
        seed = f"rate:{guild_id}:{user_id}:{now:%Y-%m-%d}:{subject.strip()}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        score = int(digest[:8], 16) % 101
        labels = FunService._list(config, "rate_labels", DEFAULT_RATE_LABELS)
        label, note = labels[-1][1], labels[-1][2]
        for upper, current_label, current_note in labels:
            if score < upper:
                label, note = current_label, current_note
                break
        return {"score": score, "label": label, "note": note}

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

    @staticmethod
    def pick_waifu(member_ids: list[int], guild_id: int, user_id: int, day: str) -> int | None:
        if not member_ids:
            return None
        sorted_ids = sorted(member_ids)
        if len(sorted_ids) == 1:
            return sorted_ids[0]

        seed = f"{guild_id}:{day}:{len(sorted_ids)}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        shift = (int(digest[:8], 16) % (len(sorted_ids) - 1)) + 1
        requester_index = sorted_ids.index(user_id) if user_id in sorted_ids else 0
        return sorted_ids[(requester_index + shift) % len(sorted_ids)]

    @staticmethod
    def lottery(
        user_id: int,
        guild_id: int,
        now: datetime | None = None,
        config: dict[str, object] | None = None,
    ) -> dict[str, object]:
        now = now or datetime.utcnow()
        seed = f"lottery:{guild_id}:{user_id}:{now:%Y-%m-%d}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        roll = int(digest[:8], 16) % 100 + 1

        threshold = 0
        rewards = FunService._list(config, "lottery_rewards", DEFAULT_LOTTERY_REWARDS)
        reward_text = rewards[-1][1]
        rarity = "common"
        for chance, text in rewards:
            threshold += chance
            if roll <= threshold:
                reward_text = text
                rarity = "legendary" if chance <= 1 else "epic" if chance <= 6 else "rare" if chance <= 18 else "common"
                break
        omen_bank = {
            "legendary": FunService._text(config, "omen_legendary", "今日天命短暂地眷顾了你。别把它浪费在发癫上。"),
            "epic": FunService._text(config, "omen_epic", "运气不错，可以尝试一些体面的整活。"),
            "rare": FunService._text(config, "omen_rare", "适合小赌怡情，不适合豪赌尊严。"),
            "common": FunService._text(config, "omen_common", "整体平稳。也就是说，任何事故大概率都算你的。"),
        }
        return {
            "roll": roll,
            "rarity": rarity,
            "text": reward_text,
            "omen": omen_bank[rarity],
        }
