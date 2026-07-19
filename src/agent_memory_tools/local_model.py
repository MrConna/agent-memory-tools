"""Small local-model adapter loaded from pi's model configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib import error, request

from .config import load_config


class LocalModel:
    def __init__(self, base_url: str, api_key: str, model: str, api: str, timeout: int = 12) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.api = api
        self.timeout = timeout

    @classmethod
    def from_pi_config(cls) -> "LocalModel | None":
        local = load_config().get("local_model", {})
        if not local.get("enabled", True) or os.environ.get("AGENT_MEMORY_LOCAL_MODEL", "auto").lower() in {"0", "off", "false"}:
            return None
        path = Path.home() / ".pi" / "agent" / "models.json"
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        providers = config.get("providers", {})
        preferred = providers.get(str(local.get("provider", "local-gemma")))
        if not isinstance(preferred, dict):
            preferred = next(
                (value for name, value in providers.items() if "gemma" in name.lower() and isinstance(value, dict)),
                None,
            )
        if not preferred or not preferred.get("baseUrl") or not preferred.get("models"):
            return None
        model = local.get("model") or preferred["models"][0].get("id")
        if not model:
            return None
        return cls(
            str(preferred["baseUrl"]), str(preferred.get("apiKey", "")),
            str(model), str(preferred.get("api", "openai-completions")),
            int(local.get("timeout_seconds", 12)),
        )

    def complete(self, prompt: str, *, max_tokens: int = 180) -> str | None:
        is_chat = self.api != "openai-completions"
        endpoint = "/chat/completions" if is_chat else "/completions"
        payload: dict[str, object] = {
            "model": self.model, "temperature": 0, "max_tokens": max_tokens,
        }
        if is_chat:
            payload["messages"] = [{"role": "user", "content": prompt}]
        else:
            payload["prompt"] = prompt
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = request.Request(
            self.base_url + endpoint, data=json.dumps(payload).encode(),
            headers=headers, method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                body = json.loads(response.read().decode())
        except (OSError, error.URLError, json.JSONDecodeError, TimeoutError):
            return None
        choices = body.get("choices") or []
        if not choices:
            return None
        choice = choices[0]
        text = choice.get("text") or (choice.get("message") or {}).get("content")
        return str(text).strip() if text else None

    def compress_observation(self, text: str) -> str | None:
        return self.complete(
            "Compress this coding-agent event into one factual sentence (max 40 words). "
            "Keep file names, commands, outcomes, and errors. Do not infer. Output only the sentence.\n\n"
            + text[:8000],
            max_tokens=100,
        )

    def summarize_session(self, observations: list[str]) -> str | None:
        return self.complete(
            "Summarize these coding-agent observations in at most 5 concise factual bullets. "
            "Separate completed work, errors, and remaining signals. Do not invent decisions.\n\n"
            + "\n".join(observations[-30:]),
            max_tokens=260,
        )
