from __future__ import annotations

import json
import os
import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.core.config import EnvSettings


USER_AGENT = "DC_Bot/0.1 (Discord entertainment bot)"


@dataclass
class ImageSiteSpec:
    name: str
    adapter: str
    base_url: str
    post_base_url: str
    user_id: str | None = None
    username: str | None = None
    api_key: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class ImageSiteProfile:
    name: str
    site: str
    supports_safe: bool = True
    supports_explicit: bool = True
    description: str = ""
    defaults: dict[str, Any] = field(default_factory=dict)


class ImageSourceRouter:
    def __init__(self, env: EnvSettings) -> None:
        self.env = env
        self._dotenv_cache: dict[str, str] | None = None

    async def random_post(
        self,
        *,
        profile: str,
        rating_mode: str,
        base_tags: str = "",
        extra_tags: str = "",
    ) -> dict[str, Any]:
        sites, profiles = self._load_registry()
        profile_spec = profiles.get(profile)
        if profile_spec is None:
            raise RuntimeError(f"未找到图站档案 `{profile}`。")
        site_spec = sites.get(profile_spec.site)
        if site_spec is None:
            raise RuntimeError(f"图站 `{profile_spec.site}` 不存在。")

        if rating_mode == "safe" and not profile_spec.supports_safe:
            raise RuntimeError(f"`{profile}` 不支持安全模式图片，请换成别的图站或改用涩图模式。")
        if rating_mode == "explicit" and not profile_spec.supports_explicit:
            raise RuntimeError(f"`{profile}` 不支持涩图模式图片。")

        merged_tags = self._merge_tags(base_tags, extra_tags)
        if site_spec.adapter == "danbooru":
            return await self._random_danbooru_post(site_spec, merged_tags, rating_mode)
        if site_spec.adapter == "rule34":
            return await self._random_rule34_post(site_spec, merged_tags, rating_mode)
        raise RuntimeError(f"不支持的图站适配器 `{site_spec.adapter}`。")

    def list_profiles(self) -> dict[str, dict[str, object]]:
        sites, profiles = self._load_registry()
        return {
            name: {
                "site": spec.site,
                "adapter": sites[spec.site].adapter if spec.site in sites else "",
                "supports_safe": spec.supports_safe,
                "supports_explicit": spec.supports_explicit,
                "description": spec.description,
            }
            for name, spec in profiles.items()
        }

    def _load_registry(self) -> tuple[dict[str, ImageSiteSpec], dict[str, ImageSiteProfile]]:
        sites = self._default_sites()
        profiles = self._default_profiles()
        provider_file = self.env.ai_provider_file
        if provider_file.exists():
            try:
                raw = json.loads(provider_file.read_text(encoding="utf-8"))
            except Exception:
                raw = {}
            if isinstance(raw, dict):
                for name, payload in raw.get("image_sites", {}).items():
                    spec = self._site_from_payload(name, payload)
                    if spec is not None:
                        sites[name] = spec
                for name, payload in raw.get("image_site_profiles", {}).items():
                    spec = self._profile_from_payload(name, payload)
                    if spec is not None:
                        profiles[name] = spec
        return sites, profiles

    def _default_sites(self) -> dict[str, ImageSiteSpec]:
        return {
            "danbooru": ImageSiteSpec(
                name="danbooru",
                adapter="danbooru",
                base_url=self.env.danbooru_base_url.rstrip("/"),
                post_base_url=self.env.danbooru_base_url.rstrip("/"),
                username=self.env.danbooru_username,
                api_key=self.env.danbooru_api_key,
                headers={"User-Agent": USER_AGENT},
            ),
            "rule34": ImageSiteSpec(
                name="rule34",
                adapter="rule34",
                base_url=self.env.rule34_api_base_url.rstrip("/"),
                post_base_url=self.env.rule34_post_base_url.rstrip("/"),
                user_id=self.env.rule34_user_id,
                api_key=self.env.rule34_api_key,
                headers={"User-Agent": USER_AGENT},
            ),
        }

    @staticmethod
    def _default_profiles() -> dict[str, ImageSiteProfile]:
        return {
            "danbooru": ImageSiteProfile(
                name="danbooru",
                site="danbooru",
                supports_safe=True,
                supports_explicit=True,
                description="Danbooru，适合安全图和 NSFW 图混合使用。",
            ),
            "rule34": ImageSiteProfile(
                name="rule34",
                site="rule34",
                supports_safe=False,
                supports_explicit=True,
                description="Rule34，标签多，但更适合 NSFW / explicit 场景。",
            ),
        }

    def _site_from_payload(self, name: str, payload: object) -> ImageSiteSpec | None:
        if not isinstance(payload, dict):
            return None
        adapter = str(payload.get("adapter") or "").strip()
        base_url = self._resolve_value(payload, "base_url") or ""
        post_base_url = self._resolve_value(payload, "post_base_url") or base_url
        if not adapter or not base_url:
            return None
        headers = dict(payload.get("headers", {})) if isinstance(payload.get("headers"), dict) else {}
        headers.setdefault("User-Agent", USER_AGENT)
        return ImageSiteSpec(
            name=name,
            adapter=adapter,
            base_url=base_url.rstrip("/"),
            post_base_url=post_base_url.rstrip("/"),
            user_id=self._resolve_value(payload, "user_id"),
            username=self._resolve_value(payload, "username"),
            api_key=self._resolve_value(payload, "api_key"),
            headers=headers,
        )

    @staticmethod
    def _profile_from_payload(name: str, payload: object) -> ImageSiteProfile | None:
        if not isinstance(payload, dict):
            return None
        site = str(payload.get("site") or "").strip()
        if not site:
            return None
        return ImageSiteProfile(
            name=name,
            site=site,
            supports_safe=bool(payload.get("supports_safe", True)),
            supports_explicit=bool(payload.get("supports_explicit", True)),
            description=str(payload.get("description", "")),
            defaults=dict(payload.get("defaults", {})) if isinstance(payload.get("defaults"), dict) else {},
        )

    @staticmethod
    def _merge_tags(base_tags: str, extra_tags: str) -> str:
        return " ".join(part.strip() for part in [base_tags, extra_tags] if part.strip()).strip()

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

    async def _random_danbooru_post(
        self,
        site: ImageSiteSpec,
        tags: str,
        rating_mode: str,
    ) -> dict[str, Any]:
        if not site.username or not site.api_key:
            raise RuntimeError("DANBOORU_USERNAME / DANBOORU_API_KEY 未配置。")

        forced_rating = "rating:s" if rating_mode == "safe" else "rating:e"
        normalized_tags = self._strip_rating_tags(tags)
        randomish_tags = f"{forced_rating} {normalized_tags} order:random".strip()
        fallback_tags = f"{forced_rating} {normalized_tags}".strip()

        auth = (site.username, site.api_key)
        async with httpx.AsyncClient(auth=auth, headers=site.headers, timeout=30.0) as client:
            randomish_response = await client.get(
                f"{site.base_url}/posts.json",
                params={"limit": 20, "tags": randomish_tags},
            )
            if randomish_response.is_success:
                items = randomish_response.json()
                if items:
                    return self._normalize_danbooru_post(site, random.choice(items))

            fallback_response = await client.get(
                f"{site.base_url}/posts.json",
                params={"limit": 20, "tags": fallback_tags or None},
            )
            if fallback_response.is_error:
                raise RuntimeError(self._format_http_error("Danbooru", fallback_response))
            items = fallback_response.json()

        if not items:
            raise RuntimeError("Danbooru 没有找到符合条件的图片。")
        return self._normalize_danbooru_post(site, random.choice(items))

    async def _random_rule34_post(
        self,
        site: ImageSiteSpec,
        tags: str,
        rating_mode: str,
    ) -> dict[str, Any]:
        if rating_mode != "explicit":
            raise RuntimeError("Rule34 目前只开放给涩图模式。")
        if not site.user_id or not site.api_key:
            raise RuntimeError("RULE34_USER_ID / RULE34_API_KEY 未配置。")

        query_tags = self._strip_rating_tags(tags)
        async with httpx.AsyncClient(headers=site.headers, timeout=30.0) as client:
            response = await client.get(
                f"{site.base_url}/index.php",
                params={
                    "page": "dapi",
                    "s": "post",
                    "q": "index",
                    "json": 1,
                    "limit": 100,
                    "user_id": site.user_id,
                    "api_key": site.api_key,
                    "tags": query_tags or None,
                },
            )
        if response.is_error:
            raise RuntimeError(self._format_http_error("Rule34", response))

        items = self._decode_rule34_response(response)
        if not items:
            raise RuntimeError("Rule34 没有找到符合条件的图片。")
        return self._normalize_rule34_post(site, random.choice(items))

    @staticmethod
    def _decode_rule34_response(response: httpx.Response) -> list[dict[str, Any]]:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = None

        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            posts = payload.get("posts")
            if isinstance(posts, list):
                return [item for item in posts if isinstance(item, dict)]

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            return []
        items: list[dict[str, Any]] = []
        for post in root.findall(".//post"):
            items.append(post.attrib)
        return items

    @staticmethod
    def _strip_rating_tags(tags: str) -> str:
        cleaned = tags
        for token in ("rating:s", "rating:e", "rating:q", "rating:safe", "rating:explicit", "rating:general"):
            cleaned = cleaned.replace(token, " ")
        return " ".join(cleaned.split())

    @staticmethod
    def _normalize_danbooru_post(site: ImageSiteSpec, post: dict[str, Any]) -> dict[str, Any]:
        file_url = post.get("file_url") or post.get("large_file_url") or ""
        if isinstance(file_url, str) and file_url.startswith("//"):
            file_url = f"https:{file_url}"
        elif isinstance(file_url, str) and file_url.startswith("/"):
            file_url = f"{site.post_base_url}{file_url}"

        return {
            "id": post.get("id"),
            "rating": post.get("rating"),
            "tags": post.get("tag_string", ""),
            "source": post.get("source"),
            "file_url": file_url,
            "post_url": f"{site.post_base_url}/posts/{post.get('id')}",
            "site": site.name,
            "site_label": "Danbooru",
        }

    @staticmethod
    def _normalize_rule34_post(site: ImageSiteSpec, post: dict[str, Any]) -> dict[str, Any]:
        file_url = (
            post.get("file_url")
            or post.get("sample_url")
            or post.get("jpeg_url")
            or ""
        )
        post_id = post.get("id")
        return {
            "id": post_id,
            "rating": post.get("rating", "explicit"),
            "tags": post.get("tags", ""),
            "source": post.get("source"),
            "file_url": file_url,
            "post_url": f"{site.post_base_url}/index.php?page=post&s=view&id={post_id}",
            "site": site.name,
            "site_label": "Rule34",
        }

    @staticmethod
    def _format_http_error(label: str, response: httpx.Response) -> str:
        body = response.text[:500]
        return f"{label} HTTP {response.status_code}: {body}"
