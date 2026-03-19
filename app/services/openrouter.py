from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import EnvSettings


LOGGER = logging.getLogger(__name__)
THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


@dataclass
class ProviderSpec:
    name: str
    api_key: str | None
    base_url: str
    default_chat_model: str = ""
    chat_path: str = "/chat/completions"
    site_url: str | None = None
    site_name: str | None = None
    draw_api_key: str | None = None
    draw_base_url: str | None = None
    default_draw_model: str = ""
    draw_path: str = "/draw/completions"
    draw_result_path: str = "/draw/result"

    def chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.chat_path.lstrip('/')}"

    def draw_submit_url(self) -> str:
        return f"{(self.draw_base_url or self.base_url).rstrip('/')}/{self.draw_path.lstrip('/')}"

    def draw_result_url(self) -> str:
        return f"{(self.draw_base_url or self.base_url).rstrip('/')}/{self.draw_result_path.lstrip('/')}"

    def resolved_draw_api_key(self) -> str | None:
        return self.draw_api_key or self.api_key


class OpenRouterClient:
    def __init__(self, env: EnvSettings) -> None:
        self.env = env

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        provider: str | None = None,
        fallback_providers: str | list[str] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 800,
    ) -> str:
        errors: list[str] = []
        for name, spec in self._iter_chat_providers(provider, fallback_providers):
            if spec is None:
                errors.append(f"{name}: 渠道不存在")
                continue
            chat_model = (model or spec.default_chat_model).strip()
            if not spec.api_key:
                errors.append(f"{name}: 未配置 api_key")
                continue
            if not chat_model:
                errors.append(f"{name}: 未配置聊天模型")
                continue

            payload = {
                "model": chat_model,
                "stream": False,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            try:
                data = await self._post_json(
                    spec.chat_url(),
                    headers=self._chat_headers(spec),
                    payload=payload,
                    timeout=45.0,
                )
                normalized = self._normalize_payload(data)
                content = normalized["choices"][0]["message"]["content"]
                return self._sanitize_assistant_text(self._flatten_content(content))
            except Exception as exc:  # pragma: no cover - network bound
                LOGGER.warning("AI chat provider %s failed: %s", name, self._describe_exception(exc))
                errors.append(f"{name}: {self._describe_exception(exc)}")

        raise RuntimeError(self._join_provider_errors("AI 对话", errors))

    async def draw(
        self,
        *,
        prompt: str,
        model: str | None = None,
        provider: str | None = None,
        fallback_providers: str | list[str] | None = None,
        size: str = "1:1",
        variants: int = 1,
        urls: list[str] | None = None,
        web_hook: str | None = None,
        shut_progress: bool = False,
    ) -> dict[str, Any]:
        errors: list[str] = []
        for name, spec in self._iter_draw_providers(provider, fallback_providers):
            if spec is None:
                errors.append(f"{name}: 渠道不存在")
                continue
            draw_model = (model or spec.default_draw_model).strip()
            draw_api_key = spec.resolved_draw_api_key()
            if not draw_api_key:
                errors.append(f"{name}: 未配置 draw api_key")
                continue
            if not draw_model:
                errors.append(f"{name}: 未配置绘图模型")
                continue

            payload: dict[str, Any] = {
                "model": draw_model,
                "prompt": prompt,
                "size": size,
                "variants": variants,
                "shutProgress": shut_progress,
                "webHook": "-1" if web_hook is None else web_hook,
            }
            if urls:
                payload["urls"] = urls

            try:
                data = await self._post_json(
                    spec.draw_submit_url(),
                    headers=self._draw_headers(draw_api_key),
                    payload=payload,
                    timeout=120.0,
                )
                normalized = self._normalize_draw_payload(data)
                normalized["_provider"] = name
                return normalized
            except Exception as exc:  # pragma: no cover - network bound
                LOGGER.warning("AI draw provider %s failed: %s", name, self._describe_exception(exc))
                errors.append(f"{name}: {self._describe_exception(exc)}")

        raise RuntimeError(self._join_provider_errors("AI 绘图", errors))

    async def draw_result(self, task_id: str, *, provider: str | None = None) -> dict[str, Any]:
        provider_name = provider or self.env.ai_draw_provider or "legacy"
        specs = self._load_provider_specs()
        spec = specs.get(provider_name)
        if spec is None:
            raise RuntimeError(f"未找到绘图渠道 `{provider_name}`。")

        draw_api_key = spec.resolved_draw_api_key()
        if not draw_api_key:
            raise RuntimeError(f"绘图渠道 `{provider_name}` 未配置 api_key。")

        try:
            return self._normalize_draw_payload(
                await self._post_json(
                    spec.draw_result_url(),
                    headers=self._draw_headers(draw_api_key),
                    payload={"id": task_id},
                    timeout=45.0,
                )
            )
        except Exception as exc:  # pragma: no cover - network bound
            raise RuntimeError(f"{provider_name}: {self._describe_exception(exc)}") from exc

    async def summarize_text(
        self,
        system_prompt: str,
        text: str,
        *,
        model: str | None = None,
        provider: str | None = None,
        fallback_providers: str | list[str] | None = None,
    ) -> str:
        return await self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            model=model,
            provider=provider,
            fallback_providers=fallback_providers,
            temperature=0.4,
            max_tokens=700,
        )

    def list_providers(self) -> dict[str, dict[str, object]]:
        providers = self._load_provider_specs()
        return {
            name: {
                "chat_url": spec.chat_url(),
                "draw_url": spec.draw_submit_url(),
                "chat_model": spec.default_chat_model,
                "draw_model": spec.default_draw_model,
                "chat_ready": bool(spec.api_key and spec.base_url),
                "draw_ready": bool(spec.resolved_draw_api_key() and (spec.draw_base_url or spec.base_url)),
            }
            for name, spec in providers.items()
        }

    def _load_provider_specs(self) -> dict[str, ProviderSpec]:
        providers: dict[str, ProviderSpec] = {
            "legacy": ProviderSpec(
                name="legacy",
                api_key=self.env.openrouter_api_key,
                base_url=self.env.openrouter_base_url,
                default_chat_model=self.env.openrouter_model,
                site_url=self.env.openrouter_site_url,
                site_name=self.env.openrouter_site_name,
                draw_api_key=self.env.draw_api_key,
                draw_base_url=self.env.draw_base_url,
                default_draw_model=self.env.draw_model,
            )
        }

        if self.env.ai_provider_file.exists():
            try:
                raw = json.loads(self.env.ai_provider_file.read_text(encoding="utf-8"))
                payload = raw.get("providers", raw) if isinstance(raw, dict) else {}
            except Exception as exc:
                LOGGER.warning("Failed to load provider file %s: %s", self.env.ai_provider_file, exc)
                payload = {}
            if isinstance(payload, dict):
                for name, item in payload.items():
                    if not isinstance(item, dict) or not item.get("base_url"):
                        continue
                    providers[name] = ProviderSpec(
                        name=name,
                        api_key=self._resolve_secret(item, "api_key"),
                        base_url=str(item["base_url"]),
                        default_chat_model=str(item.get("default_chat_model", "")),
                        chat_path=str(item.get("chat_path", "/chat/completions")),
                        site_url=item.get("site_url"),
                        site_name=item.get("site_name"),
                        draw_api_key=self._resolve_secret(item, "draw_api_key"),
                        draw_base_url=item.get("draw_base_url"),
                        default_draw_model=str(item.get("default_draw_model", "")),
                        draw_path=str(item.get("draw_path", "/draw/completions")),
                        draw_result_path=str(item.get("draw_result_path", "/draw/result")),
                    )
        return providers

    @staticmethod
    def _resolve_secret(payload: dict[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if value:
            return str(value)
        env_name = payload.get(f"{key}_env")
        if env_name:
            resolved = os.getenv(str(env_name))
            if resolved:
                return resolved
        return None

    def _iter_chat_providers(
        self,
        provider: str | None,
        fallback_providers: str | list[str] | None,
    ) -> list[tuple[str, ProviderSpec | None]]:
        return self._resolve_provider_chain(provider or self.env.ai_chat_provider, fallback_providers or self.env.ai_chat_fallbacks)

    def _iter_draw_providers(
        self,
        provider: str | None,
        fallback_providers: str | list[str] | None,
    ) -> list[tuple[str, ProviderSpec | None]]:
        return self._resolve_provider_chain(provider or self.env.ai_draw_provider, fallback_providers or self.env.ai_draw_fallbacks)

    def _resolve_provider_chain(
        self,
        provider: str,
        fallback_providers: str | list[str] | None,
    ) -> list[tuple[str, ProviderSpec | None]]:
        specs = self._load_provider_specs()
        names: list[str] = []
        for raw in [provider, *(fallback_providers if isinstance(fallback_providers, list) else str(fallback_providers or "").split(","))]:
            name = str(raw).strip()
            if name and name not in names:
                names.append(name)
        if not names:
            names = ["legacy"]
        return [(name, specs.get(name)) for name in names]

    async def _post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
    ) -> Any:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise RuntimeError("请求超时，渠道可能挂了或响应过慢。") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"请求发送失败：{exc.__class__.__name__}") from exc

        if response.is_error:
            raise RuntimeError(self._format_http_error(response))
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"接口返回了非 JSON 内容：{response.text[:500]}") from exc

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

    @staticmethod
    def _normalize_draw_payload(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected draw response: {payload!r}")
        code = payload.get("code")
        if code not in {None, 0, 200} and payload.get("data") is None:
            raise RuntimeError(f"Draw provider error {code}: {payload.get('msg', 'Unknown error')}")
        return payload

    @staticmethod
    def _chat_headers(spec: ProviderSpec) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {spec.api_key}",
            "Content-Type": "application/json",
        }
        if spec.site_url:
            headers["HTTP-Referer"] = spec.site_url
        if spec.site_name:
            headers["X-Title"] = spec.site_name
        return headers

    @staticmethod
    def _draw_headers(api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _format_http_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            body = response.text.strip()[:500] or "<empty body>"
            return f"HTTP {response.status_code}: {body}"

        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message") or error.get("type") or "Unknown error"
                code = error.get("code", response.status_code)
                metadata = error.get("metadata")
                if metadata:
                    return f"HTTP {response.status_code} / {code}: {message} | metadata={metadata}"
                return f"HTTP {response.status_code} / {code}: {message}"

            code = payload.get("code")
            msg = payload.get("msg")
            if code is not None or msg is not None:
                return f"HTTP {response.status_code}: code={code}, msg={msg}"

        return f"HTTP {response.status_code}: {payload}"

    @staticmethod
    def _describe_exception(exc: Exception) -> str:
        text = str(exc).strip()
        return text or exc.__class__.__name__

    @staticmethod
    def _join_provider_errors(label: str, errors: list[str]) -> str:
        if not errors:
            return f"{label}失败：没有可用渠道。"
        return f"{label}失败：{' | '.join(errors)}"
