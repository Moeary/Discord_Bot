from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.core.config import EnvSettings


THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


class OpenRouterClient:
    def __init__(self, env: EnvSettings) -> None:
        self.env = env

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 800,
    ) -> str:
        if not self.env.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY 未配置。")
        if not (model or self.env.openrouter_model):
            raise RuntimeError("OPENROUTER_MODEL 未配置。")

        headers = self._chat_headers()

        payload = {
            "model": model or self.env.openrouter_model,
            "stream": False,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"{self.env.openrouter_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            if response.is_error:
                raise RuntimeError(self._format_error(response))
            data = self._normalize_payload(response.json())

        content = data["choices"][0]["message"]["content"]
        return self._sanitize_assistant_text(self._flatten_content(content))

    async def draw(
        self,
        *,
        prompt: str,
        model: str,
        size: str = "1:1",
        variants: int = 1,
        urls: list[str] | None = None,
        web_hook: str | None = None,
        shut_progress: bool = False,
    ) -> dict[str, Any]:
        draw_api_key = self.env.draw_api_key or self.env.openrouter_api_key
        if not draw_api_key:
            raise RuntimeError("DRAW_API_KEY / OPENROUTER_API_KEY 未配置。")

        headers = {
            "Authorization": f"Bearer {draw_api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "variants": variants,
            "shutProgress": shut_progress,
        }
        if urls:
            payload["urls"] = urls
        payload["webHook"] = "-1" if web_hook is None else web_hook

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.env.draw_base_url.rstrip('/')}/draw/completions",
                headers=headers,
                json=payload,
            )
            if response.is_error:
                raise RuntimeError(self._format_error(response))
            data = response.json()

        if isinstance(data, dict) and data.get("code") not in {None, 0, 200}:
            raise RuntimeError(f"Draw API error {data.get('code')}: {data.get('msg', 'Unknown error')}")
        return data

    async def draw_result(self, task_id: str) -> dict[str, Any]:
        draw_api_key = self.env.draw_api_key or self.env.openrouter_api_key
        if not draw_api_key:
            raise RuntimeError("DRAW_API_KEY / OPENROUTER_API_KEY 未配置。")

        headers = {
            "Authorization": f"Bearer {draw_api_key}",
            "Content-Type": "application/json",
        }
        payload = {"id": task_id}

        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"{self.env.draw_base_url.rstrip('/')}/draw/result",
                headers=headers,
                json=payload,
            )
            if response.is_error:
                raise RuntimeError(self._format_error(response))
            data = response.json()

        if isinstance(data, dict) and data.get("code") not in {None, 0, 200}:
            raise RuntimeError(f"Draw result error {data.get('code')}: {data.get('msg', 'Unknown error')}")
        return data

    async def summarize_text(
        self,
        system_prompt: str,
        text: str,
        *,
        model: str | None = None,
    ) -> str:
        return await self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            model=model,
            temperature=0.4,
            max_tokens=700,
        )

    @staticmethod
    def _flatten_content(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            return "\n".join(part for part in parts if part).strip()
        return str(content).strip()

    @staticmethod
    def _sanitize_assistant_text(text: str) -> str:
        cleaned = THINK_BLOCK_RE.sub("", text or "").strip()
        return cleaned or "嗯？这次模型什么都没吐出来。"

    @staticmethod
    def _normalize_payload(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected AI response: {payload!r}")

        if "choices" in payload:
            return payload

        code = payload.get("code")
        if code not in {None, 0, 200} and payload.get("data") is None:
            raise RuntimeError(f"AI provider error {code}: {payload.get('msg', 'Unknown error')}")

        data = payload.get("data")
        if isinstance(data, dict) and "choices" in data:
            return data

        raise RuntimeError(f"Unexpected AI response schema: {payload}")

    def _chat_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.env.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        if self.env.openrouter_site_url:
            headers["HTTP-Referer"] = self.env.openrouter_site_url
        if self.env.openrouter_site_name:
            headers["X-Title"] = self.env.openrouter_site_name
        return headers

    @staticmethod
    def _format_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return f"OpenRouter HTTP {response.status_code}: {response.text}"

        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            return f"OpenRouter HTTP {response.status_code}: {payload}"

        message = error.get("message", "Unknown error")
        code = error.get("code", response.status_code)
        metadata = error.get("metadata")
        if metadata:
            return f"OpenRouter error {code}: {message} | metadata={metadata}"
        return f"OpenRouter error {code}: {message}"
