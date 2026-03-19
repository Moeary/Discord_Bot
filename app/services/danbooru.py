from __future__ import annotations

import random
from typing import Any

import httpx

from app.core.config import EnvSettings


class DanbooruClient:
    def __init__(self, env: EnvSettings) -> None:
        self.env = env

    async def random_post(self, tags: str | None = None) -> dict[str, Any]:
        if not self.env.danbooru_username or not self.env.danbooru_api_key:
            raise RuntimeError("DANBOORU_USERNAME / DANBOORU_API_KEY 未配置。")

        normalized_tags = (tags or "").strip()
        auth = (self.env.danbooru_username, self.env.danbooru_api_key)
        base_url = self.env.danbooru_base_url.rstrip("/")
        headers = {"User-Agent": "DC_Bot/0.1 (Discord entertainment bot)"}

        async with httpx.AsyncClient(auth=auth, headers=headers, timeout=30.0) as client:
            randomish_response = await client.get(
                f"{base_url}/posts.json",
                params={
                    "limit": 20,
                    "tags": f"{normalized_tags} order:random".strip(),
                },
            )
            if randomish_response.is_success:
                items = randomish_response.json()
                if items:
                    return self._normalize_post(random.choice(items))

            fallback_response = await client.get(
                f"{base_url}/posts.json",
                params={
                    "limit": 20,
                    "tags": normalized_tags or None,
                },
            )
            if fallback_response.is_error:
                raise RuntimeError(self._format_error(fallback_response))
            items = fallback_response.json()

        if not items:
            raise RuntimeError("Danbooru 没有找到符合条件的图片。")
        return self._normalize_post(random.choice(items))

    def _normalize_post(self, post: dict[str, Any]) -> dict[str, Any]:
        file_url = post.get("file_url") or post.get("large_file_url") or ""
        if file_url.startswith("//"):
            file_url = f"https:{file_url}"
        elif file_url.startswith("/"):
            file_url = f"{self.env.danbooru_base_url.rstrip('/')}{file_url}"

        return {
            "id": post.get("id"),
            "rating": post.get("rating"),
            "tags": post.get("tag_string", ""),
            "source": post.get("source"),
            "file_url": file_url,
            "post_url": f"{self.env.danbooru_base_url.rstrip('/')}/posts/{post.get('id')}",
        }

    @staticmethod
    def _format_error(response: httpx.Response) -> str:
        body = response.text[:500]
        return f"Danbooru HTTP {response.status_code}: {body}"
