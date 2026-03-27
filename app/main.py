from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes.ai import router as ai_router
from app.api.routes.health import health as health_handler
from app.api.routes.health import router as health_router
from app.api.routes.settings import router as settings_router
from app.bot.client import BotManager, EntertainmentBot
from app.core.catalog import get_setting_catalog
from app.core.config import BASE_DIR, get_env_settings
from app.models.state import GlobalSettings
from app.services.ai_router import ProfiledAIClient
from app.services.image_sources import ImageSourceRouter
from app.services.personas import PersonaStore
from app.services.saucenao import SauceNaoClient
from app.services.state_store import StateStore


logging.basicConfig(level=logging.INFO)

env = get_env_settings()
store = StateStore(env.state_file)
openrouter = ProfiledAIClient(env)
image_sources = ImageSourceRouter(env)
personas = PersonaStore(env)
saucenao = SauceNaoClient(env)
bot = EntertainmentBot(
    env=env,
    store=store,
    openrouter=openrouter,
    image_sources=image_sources,
    personas=personas,
    saucenao=saucenao,
)
bot_manager = BotManager(bot, env)

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "web" / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await store.load()
    global_settings = await store.get_global_settings()
    defaults = GlobalSettings()
    updates: dict[str, object] = {}
    if getattr(global_settings, "chat_model_profile", defaults.chat_model_profile) == defaults.chat_model_profile:
        migrated_chat_profile = _migrate_chat_profile(global_settings)
        if migrated_chat_profile:
            updates["chat_model_profile"] = migrated_chat_profile
    if getattr(global_settings, "chat_fallback_profiles", defaults.chat_fallback_profiles) == defaults.chat_fallback_profiles:
        migrated_chat_fallbacks = _migrate_chat_fallbacks(global_settings)
        if migrated_chat_fallbacks:
            updates["chat_fallback_profiles"] = migrated_chat_fallbacks
    if getattr(global_settings, "draw_model_profile", defaults.draw_model_profile) == defaults.draw_model_profile:
        migrated_draw_profile = _migrate_draw_profile(global_settings)
        if migrated_draw_profile:
            updates["draw_model_profile"] = migrated_draw_profile
    if getattr(global_settings, "draw_fallback_profiles", defaults.draw_fallback_profiles) == defaults.draw_fallback_profiles:
        migrated_draw_fallbacks = _migrate_draw_fallbacks(global_settings)
        if migrated_draw_fallbacks:
            updates["draw_fallback_profiles"] = migrated_draw_fallbacks
    if updates:
        await store.update_global_settings(updates)
    await bot_manager.start()
    yield
    await bot_manager.stop()


def _migrate_chat_profile(settings: GlobalSettings) -> str:
    provider = getattr(settings, "chat_provider", "").strip()
    model = getattr(settings, "openrouter_model", "").strip()
    if provider == "grsai" and model == "gemini-3.1-pro":
        return "grsai-gemini-3.1-pro"
    if provider == "openrouter" and model == "x-ai/grok-4.1-fast":
        return "openrouter-grok-4.1-fast"
    if provider == "openrouter" and model == "openrouter/auto":
        return "openrouter-auto"
    return "legacy-chat"


def _migrate_chat_fallbacks(settings: GlobalSettings) -> str:
    raw = getattr(settings, "chat_fallback_providers", "").strip()
    if not raw:
        return ""
    mapping = {
        "legacy": "legacy-chat",
        "grsai": "grsai-gemini-3.1-pro",
        "openrouter": "openrouter-auto",
    }
    names = [mapping.get(item.strip(), item.strip()) for item in raw.split(",") if item.strip()]
    return ",".join(dict.fromkeys(names))


def _migrate_draw_profile(settings: GlobalSettings) -> str:
    provider = getattr(settings, "draw_provider", "").strip()
    model = getattr(settings, "draw_model", "").strip()
    if provider == "grsai" and model == "gpt-image-1.5":
        return "grsai-gpt-image"
    if provider == "grsai" and model in {"nano-banana-2", "nano-banana-fast"}:
        return "grsai-banana2" if model == "nano-banana-2" else "grsai-banana-fast"
    if provider in {"grsai", "legacy"} and model == "sora-image":
        return "grsai-sora-image"
    return "legacy-draw"


def _migrate_draw_fallbacks(settings: GlobalSettings) -> str:
    raw = getattr(settings, "draw_fallback_providers", "").strip()
    if not raw:
        return ""
    mapping = {
        "legacy": "legacy-draw",
        "grsai": "grsai-sora-image",
        "openrouter": "legacy-draw",
    }
    names = [mapping.get(item.strip(), item.strip()) for item in raw.split(",") if item.strip()]
    return ",".join(dict.fromkeys(names))


app = FastAPI(
    title="DC Entertainment Bot",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.env = env
app.state.store = store
app.state.openrouter = openrouter
app.state.image_sources = image_sources
app.state.personas = personas
app.state.saucenao = saucenao
app.state.bot_manager = bot_manager
app.state.health_provider = health_handler

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "web" / "static")), name="static")
app.include_router(health_router)
app.include_router(settings_router)
app.include_router(ai_router)


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/docs", response_class=HTMLResponse)
async def command_docs_page(request: Request):
    catalog = get_setting_catalog()
    commands = catalog["commands"]
    user_commands = [item for item in commands if item.get("permission", "user") == "user"]
    admin_commands = [item for item in commands if item.get("permission", "user") == "admin"]
    return templates.TemplateResponse(
        "docs.html",
        {
            "request": request,
            "catalog": catalog,
            "user_commands": user_commands,
            "admin_commands": admin_commands,
            "image_profiles": request.app.state.image_sources.list_profiles(),
            "model_profiles": request.app.state.openrouter.list_providers().get("profiles", {}),
            "personas": request.app.state.personas.list_profiles(),
        },
    )
