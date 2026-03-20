from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.core.config import EnvSettings


LOGGER = logging.getLogger(__name__)
THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
SINGLE_IMAGE_DRAW_MODELS = {"sora-image", "gpt-image-1.5"}


@dataclass
class ProviderSpec:
    name: str
    base_url: str
    api_key: str | None
    chat_path: str = "/chat/completions"
    draw_api_key: str | None = None
    draw_base_url: str | None = None
    draw_result_path: str = "/draw/result"
    site_url: str | None = None
    site_name: str | None = None

    def chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.chat_path.lstrip('/')}"

    def draw_url(self, path: str) -> str:
        base = (self.draw_base_url or self.base_url).rstrip("/")
        return f"{base}/{path.lstrip('/')}"

    def draw_result_url(self) -> str:
        return self.draw_url(self.draw_result_path)

    def resolved_draw_api_key(self) -> str | None:
        return self.draw_api_key or self.api_key


@dataclass
class ModelProfile:
    name: str
    kind: str
    provider: str
    adapter: str
    model: str
    defaults: dict[str, Any] = field(default_factory=dict)
    request_path: str | None = None
    result_path: str | None = None
    description: str = ""


class ProfiledAIClient:
    def __init__(self, env: EnvSettings) -> None:
        self.env = env
        self._dotenv_cache: dict[str, str] | None = None

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        profile: str | None = None,
        fallback_profiles: str | list[str] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 800,
    ) -> str:
        errors: list[str] = []
        providers, profiles = self._load_registry()
        for profile_name, profile_spec in self._resolve_profile_chain(
            profiles,
            profile or "legacy-chat",
            fallback_profiles,
            kind="chat",
        ):
            if profile_spec is None:
                errors.append(f"{profile_name}: 档案不存在")
                continue
            provider_spec = providers.get(profile_spec.provider)
            if provider_spec is None:
                errors.append(f"{profile_name}: 渠道 `{profile_spec.provider}` 不存在")
                continue
            if profile_spec.adapter != "openai_chat":
                errors.append(f"{profile_name}: 不支持的聊天适配器 `{profile_spec.adapter}`")
                continue
            if not provider_spec.api_key:
                errors.append(f"{profile_name}: 未配置 api_key")
                continue

            payload = {
                "model": (model or profile_spec.model).strip(),
                "stream": False,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if not payload["model"]:
                errors.append(f"{profile_name}: 未配置聊天模型")
                continue

            try:
                data = await self._post_json(
                    provider_spec.chat_url(),
                    headers=self._chat_headers(provider_spec),
                    payload=payload,
                    timeout=45.0,
                )
                normalized = self._normalize_chat_payload(data)
                content = normalized["choices"][0]["message"]["content"]
                return self._sanitize_assistant_text(self._flatten_content(content))
            except Exception as exc:  # pragma: no cover - network bound
                LOGGER.warning("AI chat profile %s failed: %s", profile_name, self._describe_exception(exc))
                errors.append(f"{profile_name}: {self._describe_exception(exc)}")

        raise RuntimeError(self._join_errors("AI 对话", errors))

    async def draw(
        self,
        *,
        prompt: str,
        model: str | None = None,
        profile: str | None = None,
        fallback_profiles: str | list[str] | None = None,
        size: str = "1:1",
        variants: int = 1,
        urls: list[str] | None = None,
        web_hook: str | None = None,
        shut_progress: bool = False,
    ) -> dict[str, Any]:
        errors: list[str] = []
        providers, profiles = self._load_registry()
        for profile_name, profile_spec in self._resolve_profile_chain(
            profiles,
            profile or "legacy-draw",
            fallback_profiles,
            kind="draw",
        ):
            if profile_spec is None:
                errors.append(f"{profile_name}: 档案不存在")
                continue
            provider_spec = providers.get(profile_spec.provider)
            if provider_spec is None:
                errors.append(f"{profile_name}: 渠道 `{profile_spec.provider}` 不存在")
                continue
            draw_api_key = provider_spec.resolved_draw_api_key()
            if not draw_api_key:
                errors.append(f"{profile_name}: 未配置 draw api_key")
                continue

            draw_model = (model or profile_spec.model).strip()
            if not draw_model:
                errors.append(f"{profile_name}: 未配置绘图模型")
                continue

            try:
                request_path, payload, warning = self._build_draw_request_payload(
                    profile_spec,
                    prompt=prompt,
                    draw_model=draw_model,
                    size=size,
                    variants=variants,
                    urls=urls,
                    web_hook=web_hook,
                    shut_progress=shut_progress,
                )
                data = await self._post_json(
                    provider_spec.draw_url(request_path),
                    headers=self._draw_headers(draw_api_key),
                    payload=payload,
                    timeout=120.0,
                )
                normalized = self._normalize_draw_payload(data)
                normalized["_profile"] = profile_name
                normalized["_provider"] = provider_spec.name
                if warning:
                    normalized["_warning"] = warning
                return normalized
            except Exception as exc:  # pragma: no cover - network bound
                LOGGER.warning("AI draw profile %s failed: %s", profile_name, self._describe_exception(exc))
                errors.append(f"{profile_name}: {self._describe_exception(exc)}")

        raise RuntimeError(self._join_errors("AI 绘图", errors))

    async def draw_result(
        self,
        task_id: str,
        *,
        profile: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        providers, profiles = self._load_registry()
        profile_spec: ModelProfile | None = None
        if profile:
            profile_spec = profiles.get(profile)
            if profile_spec is None:
                raise RuntimeError(f"未找到绘图档案 `{profile}`。")
        provider_name = provider or (profile_spec.provider if profile_spec else "legacy")
        provider_spec = providers.get(provider_name)
        if provider_spec is None:
            raise RuntimeError(f"未找到绘图渠道 `{provider_name}`。")

        draw_api_key = provider_spec.resolved_draw_api_key()
        if not draw_api_key:
            raise RuntimeError(f"绘图渠道 `{provider_name}` 未配置 api_key。")

        result_path = profile_spec.result_path if profile_spec and profile_spec.result_path else provider_spec.draw_result_path
        try:
            normalized = self._normalize_draw_payload(
                await self._post_json(
                    provider_spec.draw_url(result_path),
                    headers=self._draw_headers(draw_api_key),
                    payload={"id": task_id},
                    timeout=45.0,
                )
            )
        except Exception as exc:  # pragma: no cover - network bound
            raise RuntimeError(f"{provider_name}: {self._describe_exception(exc)}") from exc
        normalized["_provider"] = provider_name
        if profile_spec:
            normalized["_profile"] = profile_spec.name
        return normalized

    async def summarize_text(
        self,
        system_prompt: str,
        text: str,
        *,
        model: str | None = None,
        profile: str | None = None,
        fallback_profiles: str | list[str] | None = None,
    ) -> str:
        return await self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            model=model,
            profile=profile,
            fallback_profiles=fallback_profiles,
            temperature=0.4,
            max_tokens=700,
        )

    def list_providers(self) -> dict[str, object]:
        providers, profiles = self._load_registry()
        return {
            "providers": {
                name: {
                    "chat_url": spec.chat_url(),
                    "draw_base_url": spec.draw_url(""),
                    "chat_ready": bool(spec.api_key and spec.base_url),
                    "draw_ready": bool(spec.resolved_draw_api_key() and (spec.draw_base_url or spec.base_url)),
                }
                for name, spec in providers.items()
            },
            "profiles": {
                name: {
                    "kind": spec.kind,
                    "provider": spec.provider,
                    "adapter": spec.adapter,
                    "model": spec.model,
                    "description": spec.description,
                }
                for name, spec in profiles.items()
            },
        }

    def _load_registry(self) -> tuple[dict[str, ProviderSpec], dict[str, ModelProfile]]:
        providers = self._load_provider_specs()
        profiles = self._default_profiles()
        if self.env.ai_provider_file.exists():
            try:
                raw = json.loads(self.env.ai_provider_file.read_text(encoding="utf-8"))
            except Exception as exc:
                LOGGER.warning("Failed to load provider file %s: %s", self.env.ai_provider_file, exc)
                raw = {}

            if isinstance(raw, dict):
                for name, item in raw.get("providers", {}).items():
                    spec = self._provider_spec_from_payload(name, item)
                    if spec is not None:
                        providers[name] = spec
                for name, item in raw.get("model_profiles", raw.get("profiles", {})).items():
                    spec = self._profile_from_payload(name, item)
                    if spec is not None:
                        profiles[name] = spec
        return providers, profiles

    def _load_provider_specs(self) -> dict[str, ProviderSpec]:
        return {
            "legacy": ProviderSpec(
                name="legacy",
                base_url=self.env.openrouter_base_url,
                api_key=self.env.openrouter_api_key,
                draw_api_key=self.env.draw_api_key,
                draw_base_url=self.env.draw_base_url,
                site_url=self.env.openrouter_site_url,
                site_name=self.env.openrouter_site_name,
            )
        }

    def _default_profiles(self) -> dict[str, ModelProfile]:
        return {
            "legacy-chat": ModelProfile(
                name="legacy-chat",
                kind="chat",
                provider="legacy",
                adapter="openai_chat",
                model=self.env.openrouter_model or "gemini-3.1-pro",
                description="兼容旧版 OPENROUTER_* 配置的聊天档案。",
            ),
            "legacy-draw": ModelProfile(
                name="legacy-draw",
                kind="draw",
                provider="legacy",
                adapter="grsai_draw_completions",
                model=self.env.draw_model or "sora-image",
                description="兼容旧版 DRAW_* / OPENROUTER_* 配置的绘图档案。",
            ),
        }

    def _provider_spec_from_payload(self, name: str, payload: object) -> ProviderSpec | None:
        if not isinstance(payload, dict):
            return None
        base_url = self._resolve_value(payload, "base_url")
        if not base_url:
            return None
        return ProviderSpec(
            name=name,
            base_url=base_url,
            api_key=self._resolve_value(payload, "api_key"),
            chat_path=str(payload.get("chat_path", "/chat/completions")),
            draw_api_key=self._resolve_value(payload, "draw_api_key"),
            draw_base_url=self._resolve_value(payload, "draw_base_url"),
            draw_result_path=str(payload.get("draw_result_path", "/draw/result")),
            site_url=self._resolve_value(payload, "site_url"),
            site_name=self._resolve_value(payload, "site_name"),
        )

    def _profile_from_payload(self, name: str, payload: object) -> ModelProfile | None:
        if not isinstance(payload, dict):
            return None
        kind = str(payload.get("type") or payload.get("kind") or "").strip().lower()
        provider = str(payload.get("provider") or "").strip()
        adapter = str(payload.get("adapter") or "").strip()
        model = self._resolve_value(payload, "model") or ""
        if kind not in {"chat", "draw"} or not provider or not adapter:
            return None
        return ModelProfile(
            name=name,
            kind=kind,
            provider=provider,
            adapter=adapter,
            model=model,
            defaults=dict(payload.get("defaults", {})) if isinstance(payload.get("defaults"), dict) else {},
            request_path=str(payload.get("request_path")) if payload.get("request_path") else None,
            result_path=str(payload.get("result_path")) if payload.get("result_path") else None,
            description=str(payload.get("description", "")),
        )

    def _resolve_value(self, payload: dict[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if value not in {None, ""}:
            return str(value)
        env_name = payload.get(f"{key}_env")
        if env_name:
            resolved = self._lookup_env(str(env_name))
            if resolved:
                return resolved
        env_names = payload.get(f"{key}_envs")
        if isinstance(env_names, list):
            for candidate in env_names:
                resolved = self._lookup_env(str(candidate))
                if resolved:
                    return resolved
        return None

    def _lookup_env(self, name: str) -> str | None:
        direct = os.getenv(name)
        if direct:
            return direct
        dotenv = self._load_dotenv_map()
        return dotenv.get(name)

    def _load_dotenv_map(self) -> dict[str, str]:
        if self._dotenv_cache is not None:
            return self._dotenv_cache

        env_path = self.env.ai_provider_file.parent.parent / ".env"
        values: dict[str, str] = {}
        if Path(env_path).exists():
            for raw_line in Path(env_path).read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
        self._dotenv_cache = values
        return values

    @staticmethod
    def _resolve_profile_chain(
        profiles: dict[str, ModelProfile],
        primary: str,
        fallbacks: str | list[str] | None,
        *,
        kind: str,
    ) -> list[tuple[str, ModelProfile | None]]:
        names: list[str] = []
        sources = [primary]
        if isinstance(fallbacks, list):
            sources.extend(fallbacks)
        else:
            sources.extend(str(fallbacks or "").split(","))
        for raw in sources:
            name = str(raw).strip()
            if name and name not in names:
                names.append(name)
        if not names:
            names = [f"legacy-{kind}"]

        resolved: list[tuple[str, ModelProfile | None]] = []
        for name in names:
            profile_spec = profiles.get(name)
            if profile_spec is not None and profile_spec.kind != kind:
                resolved.append((name, None))
            else:
                resolved.append((name, profile_spec))
        return resolved

    @staticmethod
    def _build_draw_request_payload(
        profile: ModelProfile,
        *,
        prompt: str,
        draw_model: str,
        size: str,
        variants: int,
        urls: list[str] | None,
        web_hook: str | None,
        shut_progress: bool,
    ) -> tuple[str, dict[str, Any], str | None]:
        defaults = profile.defaults
        warning: str | None = None

        if profile.adapter == "grsai_draw_completions":
            safe_variants = variants
            if draw_model in SINGLE_IMAGE_DRAW_MODELS and variants > 1:
                safe_variants = 1
                warning = f"`{draw_model}` 目前只稳定支持单图生成，已自动改成 1 张。"
            payload: dict[str, Any] = {
                "model": draw_model,
                "prompt": prompt,
                "size": size or str(defaults.get("size", "1:1")),
                "variants": safe_variants,
                "webHook": "-1" if web_hook is None else web_hook,
                "shutProgress": shut_progress,
            }
            if urls:
                payload["urls"] = urls
            return profile.request_path or "/draw/completions", payload, warning

        if profile.adapter == "grsai_draw_nano_banana":
            payload = {
                "model": draw_model,
                "prompt": prompt,
                "aspectRatio": size or str(defaults.get("aspectRatio", "auto")),
                "imageSize": str(defaults.get("imageSize", "1K")),
                "webHook": "-1" if web_hook is None else web_hook,
                "shutProgress": shut_progress,
            }
            if urls:
                payload["urls"] = urls
            return profile.request_path or "/draw/nano-banana", payload, None

        raise RuntimeError(f"不支持的绘图适配器 `{profile.adapter}`")

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
    def _normalize_chat_payload(payload: Any) -> dict[str, Any]:
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
    def _join_errors(label: str, errors: list[str]) -> str:
        if not errors:
            return f"{label}失败：没有可用档案。"
        return f"{label}失败：{' | '.join(errors)}"
