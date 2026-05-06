from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import EnvSettings


class PersonaStore:
    def __init__(self, env: EnvSettings) -> None:
        self.env = env

    def list_profiles(self) -> dict[str, dict[str, object]]:
        personas = self._load_payload().get("personas", {})
        output: dict[str, dict[str, object]] = {}
        for name, payload in personas.items():
            if not isinstance(payload, dict):
                continue
            output[name] = {
                "display_name": str(payload.get("display_name", name)),
                "description": str(payload.get("description", "")),
            }
        return output

    def get_persona(self, name: str | None) -> dict[str, Any]:
        personas = self._load_payload().get("personas", {})
        profile = str(name or "glados").strip() or "glados"
        payload = personas.get(profile)
        if isinstance(payload, dict):
            return payload
        fallback = personas.get("glados")
        if isinstance(fallback, dict):
            return fallback
        return {}

    def _load_payload(self) -> dict[str, Any]:
        path = self.env.persona_file
        if not Path(path).exists():
            return {"personas": {}}
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return {"personas": {}}
        return payload if isinstance(payload, dict) else {"personas": {}}
