from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.schemas import SettingsPatchRequest
from app.core.catalog import GLOBAL_SETTING_SPECS, GUILD_SETTING_SPECS, cast_setting_value, get_setting_catalog


router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/dashboard")
async def dashboard(request: Request, guild_id: int | None = Query(default=None)) -> dict[str, object]:
    store = request.app.state.store
    snapshot = await store.get_snapshot()
    selected_guild = snapshot.guilds.get(str(guild_id)) if guild_id else None
    return {
        "health": await request.app.state.health_provider(request),
        "catalog": get_setting_catalog(),
        "providers": request.app.state.openrouter.list_providers(),
        "global_settings": snapshot.global_settings.model_dump(),
        "guilds": {
            guild_key: guild_settings.model_dump()
            for guild_key, guild_settings in snapshot.guilds.items()
        },
        "selected_guild_settings": selected_guild.model_dump() if selected_guild else None,
        "pending_tax_cases": [
            tax_case.model_dump(mode="json")
            for tax_case in snapshot.tax_cases
            if tax_case.status == "pending" and (guild_id is None or tax_case.guild_id == guild_id)
        ],
        "stats": {
            guild_key: guild_stats.model_dump()
            for guild_key, guild_stats in snapshot.stats.items()
        },
    }


@router.get("/settings/global")
async def get_global_settings(request: Request) -> dict[str, object]:
    settings = await request.app.state.store.get_global_settings()
    return settings.model_dump()


@router.patch("/settings/global")
async def patch_global_settings(request: Request, payload: SettingsPatchRequest) -> dict[str, object]:
    updates: dict[str, object] = {}
    for key, value in payload.updates.items():
        if key not in GLOBAL_SETTING_SPECS:
            raise HTTPException(status_code=400, detail=f"未知全局配置项: {key}")
        try:
            updates[key] = cast_setting_value(GLOBAL_SETTING_SPECS, key, value)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    settings = await request.app.state.store.update_global_settings(updates)
    return settings.model_dump()


@router.get("/settings/guild/{guild_id}")
async def get_guild_settings(request: Request, guild_id: int) -> dict[str, object]:
    settings = await request.app.state.store.get_guild_settings(guild_id)
    return settings.model_dump()


@router.patch("/settings/guild/{guild_id}")
async def patch_guild_settings(
    request: Request,
    guild_id: int,
    payload: SettingsPatchRequest,
) -> dict[str, object]:
    updates: dict[str, object] = {}
    for key, value in payload.updates.items():
        if key not in GUILD_SETTING_SPECS:
            raise HTTPException(status_code=400, detail=f"未知服务器配置项: {key}")
        try:
            updates[key] = cast_setting_value(GUILD_SETTING_SPECS, key, value)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    settings = await request.app.state.store.update_guild_settings(guild_id, updates)
    return settings.model_dump()


@router.get("/tax/pending")
async def get_pending_tax(request: Request, guild_id: int | None = Query(default=None)) -> list[dict[str, object]]:
    cases = await request.app.state.store.list_tax_cases(status="pending", guild_id=guild_id)
    return [tax_case.model_dump(mode="json") for tax_case in cases]


@router.get("/stats/{guild_id}")
async def get_stats(request: Request, guild_id: int) -> dict[str, object]:
    snapshot = await request.app.state.store.get_snapshot()
    stats = snapshot.stats.get(str(guild_id))
    return stats.model_dump() if stats else {"total_tax_cases": 0, "user_stats": {}}
