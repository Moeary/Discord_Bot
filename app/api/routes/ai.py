from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.schemas import ChatRequest, DrawRequest, DrawResultRequest, SummaryRequest


router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/chat")
async def chat(request: Request, payload: ChatRequest) -> dict[str, str]:
    store = request.app.state.store
    global_settings = await store.get_global_settings()
    user_content: str | list[dict[str, object]] = payload.prompt
    if payload.image_urls:
        user_content = [{"type": "text", "text": payload.prompt}]
        for url in payload.image_urls:
            user_content.append({"type": "image_url", "image_url": {"url": url}})
    messages = [
        {"role": "system", "content": payload.system_prompt or global_settings.system_prompt},
        {"role": "user", "content": user_content},
    ]
    try:
        reply = await request.app.state.openrouter.chat(
            messages,
            model=payload.model or None,
            profile=payload.profile or global_settings.chat_model_profile,
            fallback_profiles=payload.fallback_profiles or global_settings.chat_fallback_profiles,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_describe_error(exc)) from exc
    return {"reply": reply}


@router.post("/summary")
async def summary(request: Request, payload: SummaryRequest) -> dict[str, str]:
    store = request.app.state.store
    global_settings = await store.get_global_settings()
    text = payload.text or "\n".join(payload.messages)
    if not payload.include_image_hints:
        text = text.replace(" [附带图片/文件]", "")
    try:
        reply = await request.app.state.openrouter.summarize_text(
            global_settings.summary_system_prompt,
            text,
            model=payload.model or None,
            profile=payload.profile or global_settings.chat_model_profile,
            fallback_profiles=payload.fallback_profiles or global_settings.chat_fallback_profiles,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_describe_error(exc)) from exc
    return {"summary": reply}


@router.post("/draw")
async def draw(request: Request, payload: DrawRequest) -> dict[str, object]:
    store = request.app.state.store
    global_settings = await store.get_global_settings()
    try:
        result = await request.app.state.openrouter.draw(
            prompt=payload.prompt,
            model=payload.model or None,
            profile=payload.profile or global_settings.draw_model_profile,
            fallback_profiles=payload.fallback_profiles or global_settings.draw_fallback_profiles,
            size=payload.size,
            variants=payload.variants,
            urls=payload.urls,
            web_hook=payload.web_hook,
            shut_progress=payload.shut_progress,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_describe_error(exc)) from exc
    return {"result": result}


@router.post("/draw/result")
async def draw_result(request: Request, payload: DrawResultRequest) -> dict[str, object]:
    try:
        result = await request.app.state.openrouter.draw_result(
            payload.id,
            profile=payload.profile,
            provider=payload.provider,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_describe_error(exc)) from exc
    return {"result": result}


def _describe_error(exc: Exception) -> str:
    text = str(exc).strip()
    return text or exc.__class__.__name__
