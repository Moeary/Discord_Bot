from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.models.state import AppState, GuildSettings, GuildStats, TaxCase, UserImagePreferences, UserStats, utcnow


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self._loaded = False
        self._state = AppState()

    async def load(self) -> None:
        async with self._lock:
            if self._loaded:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                raw = self.path.read_text(encoding="utf-8").strip()
                if raw:
                    self._state = AppState.model_validate(json.loads(raw))
            self._loaded = True

    async def _save_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            self._state.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def _ensure_guild_settings(
        self,
        guild_id: int,
        guild_name: str | None = None,
    ) -> tuple[GuildSettings, bool]:
        key = str(guild_id)
        settings = self._state.guilds.get(key)
        changed = False
        if settings is None:
            settings = GuildSettings(guild_name=guild_name or "")
            self._state.guilds[key] = settings
            changed = True
        elif guild_name and settings.guild_name != guild_name:
            settings.guild_name = guild_name
            changed = True
        return settings, changed

    def _ensure_user_stats(self, guild_id: int, user_id: int) -> UserStats:
        guild_stats = self._state.stats.setdefault(str(guild_id), GuildStats())
        return guild_stats.user_stats.setdefault(str(user_id), UserStats())

    def _ensure_user_preferences(self, guild_id: int, user_id: int) -> UserImagePreferences:
        guild_preferences = self._state.user_preferences.setdefault(str(guild_id), {})
        return guild_preferences.setdefault(str(user_id), UserImagePreferences())

    async def get_snapshot(self) -> AppState:
        await self.load()
        async with self._lock:
            return self._state.model_copy(deep=True)

    async def get_global_settings(self):
        await self.load()
        async with self._lock:
            return self._state.global_settings.model_copy(deep=True)

    async def update_global_settings(self, updates: dict[str, object]):
        await self.load()
        async with self._lock:
            for key, value in updates.items():
                setattr(self._state.global_settings, key, value)
            await self._save_unlocked()
            return self._state.global_settings.model_copy(deep=True)

    async def get_guild_settings(self, guild_id: int, guild_name: str | None = None) -> GuildSettings:
        await self.load()
        async with self._lock:
            settings, changed = self._ensure_guild_settings(guild_id, guild_name)
            if changed:
                await self._save_unlocked()
            return settings.model_copy(deep=True)

    async def update_guild_settings(
        self,
        guild_id: int,
        updates: dict[str, object],
        guild_name: str | None = None,
    ) -> GuildSettings:
        await self.load()
        async with self._lock:
            settings, _ = self._ensure_guild_settings(guild_id, guild_name)
            for key, value in updates.items():
                setattr(settings, key, value)
            await self._save_unlocked()
            return settings.model_copy(deep=True)

    async def increment_user_stat(self, guild_id: int, user_id: int, field_name: str, amount: int = 1) -> None:
        await self.load()
        async with self._lock:
            stats = self._ensure_user_stats(guild_id, user_id)
            setattr(stats, field_name, getattr(stats, field_name) + amount)
            await self._save_unlocked()

    async def get_user_preferences(self, guild_id: int, user_id: int) -> UserImagePreferences:
        await self.load()
        async with self._lock:
            preferences = self._ensure_user_preferences(guild_id, user_id)
            return preferences.model_copy(deep=True)

    async def update_user_preferences(
        self,
        guild_id: int,
        user_id: int,
        updates: dict[str, object],
    ) -> UserImagePreferences:
        await self.load()
        async with self._lock:
            preferences = self._ensure_user_preferences(guild_id, user_id)
            for key, value in updates.items():
                setattr(preferences, key, value)
            await self._save_unlocked()
            return preferences.model_copy(deep=True)

    async def add_tax_case(self, tax_case: TaxCase) -> TaxCase:
        await self.load()
        async with self._lock:
            self._state.tax_cases.append(tax_case)
            guild_stats = self._state.stats.setdefault(str(tax_case.guild_id), GuildStats())
            guild_stats.total_tax_cases += 1
            user_stats = guild_stats.user_stats.setdefault(str(tax_case.user_id), UserStats())
            user_stats.warnings += 1
            await self._save_unlocked()
            return tax_case.model_copy(deep=True)

    async def get_tax_case_for_message(self, guild_id: int, message_id: int) -> TaxCase | None:
        await self.load()
        async with self._lock:
            for tax_case in self._state.tax_cases:
                if (
                    tax_case.guild_id == guild_id
                    and tax_case.message_id == message_id
                    and tax_case.status == "pending"
                ):
                    return tax_case.model_copy(deep=True)
            return None

    async def list_tax_cases(
        self,
        status: str | None = None,
        guild_id: int | None = None,
    ) -> list[TaxCase]:
        await self.load()
        async with self._lock:
            items = [
                tax_case.model_copy(deep=True)
                for tax_case in self._state.tax_cases
                if (status is None or tax_case.status == status)
                and (guild_id is None or tax_case.guild_id == guild_id)
            ]
            return sorted(items, key=lambda item: item.created_at, reverse=True)

    async def submit_tax_images(self, guild_id: int, user_id: int, image_count: int) -> dict[str, list[TaxCase] | int]:
        await self.load()
        async with self._lock:
            pending = sorted(
                [
                    tax_case
                    for tax_case in self._state.tax_cases
                    if tax_case.guild_id == guild_id
                    and tax_case.user_id == user_id
                    and tax_case.status == "pending"
                ],
                key=lambda item: item.created_at,
            )
            updated: list[TaxCase] = []
            settled: list[TaxCase] = []
            remaining = image_count
            for tax_case in pending:
                if remaining <= 0:
                    break
                missing = tax_case.required_images - tax_case.submitted_images
                delta = min(missing, remaining)
                tax_case.submitted_images += delta
                remaining -= delta
                if tax_case.submitted_images >= tax_case.required_images:
                    tax_case.status = "paid"
                    tax_case.completed_at = utcnow()
                    stats = self._ensure_user_stats(guild_id, user_id)
                    stats.taxes_paid += 1
                    settled.append(tax_case.model_copy(deep=True))
                updated.append(tax_case.model_copy(deep=True))

            if updated:
                await self._save_unlocked()
            return {"updated": updated, "settled": settled, "remaining": remaining}

    async def expire_due_tax_cases(self) -> list[TaxCase]:
        await self.load()
        now = utcnow()
        async with self._lock:
            expired: list[TaxCase] = []
            for tax_case in self._state.tax_cases:
                if tax_case.status == "pending" and tax_case.deadline_at <= now:
                    tax_case.status = "expired"
                    tax_case.completed_at = now
                    stats = self._ensure_user_stats(tax_case.guild_id, tax_case.user_id)
                    stats.taxes_failed += 1
                    expired.append(tax_case.model_copy(deep=True))
            if expired:
                await self._save_unlocked()
            return expired
