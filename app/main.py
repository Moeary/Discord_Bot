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
from app.core.config import BASE_DIR, get_env_settings
from app.models.state import GlobalSettings
from app.services.danbooru import DanbooruClient
from app.services.openrouter import OpenRouterClient
from app.services.state_store import StateStore


logging.basicConfig(level=logging.INFO)

env = get_env_settings()
store = StateStore(env.state_file)
openrouter = OpenRouterClient(env)
danbooru = DanbooruClient(env)
bot = EntertainmentBot(env=env, store=store, openrouter=openrouter, danbooru=danbooru)
bot_manager = BotManager(bot, env)

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "web" / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await store.load()
    global_settings = await store.get_global_settings()
    defaults = GlobalSettings()
    updates: dict[str, object] = {}
    if env.openrouter_model and global_settings.openrouter_model == defaults.openrouter_model:
        updates["openrouter_model"] = env.openrouter_model
    if env.draw_model and getattr(global_settings, "draw_model", defaults.draw_model) == defaults.draw_model:
        updates["draw_model"] = env.draw_model
    if env.ai_chat_provider and getattr(global_settings, "chat_provider", defaults.chat_provider) == defaults.chat_provider:
        updates["chat_provider"] = env.ai_chat_provider
    if getattr(global_settings, "chat_fallback_providers", defaults.chat_fallback_providers) == defaults.chat_fallback_providers:
        updates["chat_fallback_providers"] = env.ai_chat_fallbacks
    if env.ai_draw_provider and getattr(global_settings, "draw_provider", defaults.draw_provider) == defaults.draw_provider:
        updates["draw_provider"] = env.ai_draw_provider
    if getattr(global_settings, "draw_fallback_providers", defaults.draw_fallback_providers) == defaults.draw_fallback_providers:
        updates["draw_fallback_providers"] = env.ai_draw_fallbacks
    if updates:
        await store.update_global_settings(updates)
    await bot_manager.start()
    yield
    await bot_manager.stop()


app = FastAPI(
    title="DC Entertainment Bot",
    version="0.1.0",
    lifespan=lifespan,
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
app.state.danbooru = danbooru
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
