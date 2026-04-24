from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import requests

from app.core.config import settings


class LLMService:
    def is_available(self) -> bool:
        return bool(settings.llm_api_key and settings.llm_base_url and settings.llm_model_id)

    def _chat(self, messages: List[Dict[str, Any]], temperature: float = 0.1) -> str:
        if not self.is_available():
            raise RuntimeError("LLM configuration is not available.")
        url = settings.llm_base_url.rstrip("/") + "/chat/completions"
        payload: Dict[str, Any] = {
            "model": settings.llm_model_id,
            "messages": messages,
            "temperature": temperature,
        }
        if settings.llm_enable_thinking:
            payload["enable_thinking"] = True
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=settings.llm_timeout,
        )
        response.raise_for_status()
        data = response.json()
        choices: List[Dict[str, Any]] = data.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            return "\n".join(parts).strip()
        return str(content).strip()

    def summarize(self, system_prompt: str, user_prompt: str) -> str:
        return self._chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )

    def plan_json(self, system_prompt: str, user_prompt: str) -> Optional[Dict[str, Any]]:
        raw = self._chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    return None
        return None
