from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import EnvSettings


class SauceNaoClient:
    def __init__(self, env: EnvSettings) -> None:
        self.env = env

    async def search(self, image_url: str, *, numres: int = 6) -> dict[str, Any]:
        if not self.env.saucenao_api_key:
            raise RuntimeError("SAUCENAO_API_KEY 未配置。")
        params = {
            "output_type": 2,
            "api_key": self.env.saucenao_api_key,
            "numres": max(1, min(numres, 10)),
            "url": image_url,
        }
        async with httpx.AsyncClient(timeout=45.0, headers={"User-Agent": "DC_Bot/0.1"}) as client:
            response = await client.get(self.env.saucenao_base_url, params=params)
        if response.is_error:
            raise RuntimeError(self._format_error(response))
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"SauceNAO 返回了非 JSON 内容：{response.text[:300]}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected SauceNAO response: {payload!r}")
        header = payload.get("header")
        results = payload.get("results")
        if not isinstance(header, dict) or not isinstance(results, list):
            raise RuntimeError(f"Unexpected SauceNAO schema: {payload}")
        return payload

    @staticmethod
    def _format_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return f"SauceNAO HTTP {response.status_code}: {response.text[:300]}"
        return f"SauceNAO HTTP {response.status_code}: {payload}"
