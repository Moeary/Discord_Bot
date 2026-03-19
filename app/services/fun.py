from __future__ import annotations

import hashlib
import random
from datetime import datetime


FORTUNE_TEXT = [
    "大吉，今天你的计划看起来居然像是经过思考。",
    "中吉，谨慎一点，你仍然可能成功。",
    "小吉，别太兴奋，稳定发挥就行。",
    "平，你今天最大的成就是没有把事情弄得更糟。",
    "小凶，冲动是把你送进节目效果区的直通车。",
    "大凶，建议先深呼吸，再决定要不要发那张图。",
]

EIGHT_BALL_TEXT = [
    "答案是肯定的。令人遗憾，但确实如此。",
    "大概率会成。别把好运浪费在低级失误上。",
    "可以冲，但后果你自己背。",
    "我建议再等等，你现在像在拿脸接子弹。",
    "不太行，宇宙都在劝你冷静。",
    "绝无可能。至少今天不行。",
]


LOTTERY_REWARDS = [
    (1, "传说级奖励：你今天说话有 5% 概率没人反驳。"),
    (6, "史诗级奖励：本日 Danbooru 首抽命中率提升。"),
    (18, "稀有奖励：今天适合点到为止地整活。"),
    (35, "普通奖励：你获得了一份心理安慰。"),
    (40, "安慰奖：至少你还在呼吸。"),
]


class FunService:
    @staticmethod
    def daily_fortune(user_id: int, guild_id: int, now: datetime | None = None) -> dict[str, object]:
        now = now or datetime.utcnow()
        seed = f"{guild_id}:{user_id}:{now:%Y-%m-%d}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        score = int(digest[:8], 16) % 101
        text = FORTUNE_TEXT[min(score // 17, len(FORTUNE_TEXT) - 1)]
        return {"score": score, "text": text}

    @staticmethod
    def roulette() -> dict[str, object]:
        chamber = random.randint(1, 6)
        safe = chamber != 1
        return {
            "safe": safe,
            "chamber": chamber,
            "text": "咔哒，你暂时被系统判定为还能继续说话。" if safe else "砰，节目效果完美命中。",
        }

    @staticmethod
    def coinflip(user_id: int, guild_id: int, now: datetime | None = None) -> dict[str, str]:
        now = now or datetime.utcnow()
        seed = f"coin:{guild_id}:{user_id}:{now:%Y-%m-%d:%H}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        head = int(digest[:2], 16) % 2 == 0
        return {
            "side": "正面" if head else "反面",
            "text": "宇宙替你掷了一次硬币。它显然也没有更好的计划。",
        }

    @staticmethod
    def choose(options: list[str], guild_id: int, user_id: int, now: datetime | None = None) -> dict[str, object]:
        cleaned = [option.strip() for option in options if option.strip()]
        if len(cleaned) < 2:
            raise ValueError("至少给我两个选项，不然这不叫选择，叫自言自语。")
        now = now or datetime.utcnow()
        seed = f"choose:{guild_id}:{user_id}:{now:%Y-%m-%d}:{'|'.join(cleaned)}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % len(cleaned)
        return {"choice": cleaned[index], "options": cleaned}

    @staticmethod
    def eight_ball(question: str, guild_id: int, user_id: int, now: datetime | None = None) -> dict[str, str]:
        now = now or datetime.utcnow()
        seed = f"8ball:{guild_id}:{user_id}:{now:%Y-%m-%d}:{question.strip()}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % len(EIGHT_BALL_TEXT)
        return {"answer": EIGHT_BALL_TEXT[index]}

    @staticmethod
    def ship_score(left_id: int, right_id: int, guild_id: int, day: str) -> dict[str, object]:
        pair = ":".join(str(value) for value in sorted([left_id, right_id]))
        digest = hashlib.sha256(f"ship:{guild_id}:{day}:{pair}".encode("utf-8")).hexdigest()
        score = int(digest[:8], 16) % 101
        if score >= 90:
            label = "核反应堆级绑定"
        elif score >= 70:
            label = "高温暧昧"
        elif score >= 45:
            label = "能聊，但别急着办酒"
        elif score >= 20:
            label = "塑料电波"
        else:
            label = "建议保持社交距离"
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
    def lottery(user_id: int, guild_id: int, now: datetime | None = None) -> dict[str, object]:
        now = now or datetime.utcnow()
        seed = f"lottery:{guild_id}:{user_id}:{now:%Y-%m-%d}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        roll = int(digest[:8], 16) % 100 + 1

        threshold = 0
        reward_text = LOTTERY_REWARDS[-1][1]
        rarity = "common"
        for chance, text in LOTTERY_REWARDS:
            threshold += chance
            if roll <= threshold:
                reward_text = text
                rarity = "legendary" if chance <= 1 else "epic" if chance <= 6 else "rare" if chance <= 18 else "common"
                break
        omen_bank = {
            "legendary": "今日天命站在你这边，记得别把它浪费在发癫上。",
            "epic": "运气不错，可以考虑做点平时不敢做的小整活。",
            "rare": "今天适合小赌怡情，不适合豪赌人生。",
            "common": "平稳的一天。也就是说，任何事故多半都由你自己负责。",
        }
        return {
            "roll": roll,
            "rarity": rarity,
            "text": reward_text,
            "omen": omen_bank[rarity],
        }
