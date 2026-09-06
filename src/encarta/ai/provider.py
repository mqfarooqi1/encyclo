"""AI provider abstraction.

The application must never depend on a cloud API to be useful. Providers are
pluggable and the default is ``NullProvider``, which does not guess: it reports
that generation is unavailable and lets the caller fall back to showing
retrieved encyclopaedia content instead.

Adding a provider means implementing ``complete()``. No other layer changes.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..config import Config

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Completion:
    text: str
    model: str
    available: bool = True
    reason: str | None = None


class AIProvider(ABC):
    name: str = "none"

    @abstractmethod
    def complete(self, system: str, prompt: str, *, max_tokens: int = 900) -> Completion: ...

    @property
    def available(self) -> bool:
        return False


class NullProvider(AIProvider):
    """The default. Declines rather than inventing."""

    name = "none"

    def complete(self, system: str, prompt: str, *, max_tokens: int = 900) -> Completion:
        return Completion(
            text="",
            model="none",
            available=False,
            reason=(
                "No AI provider is configured. The encyclopaedia is answering from its "
                "own indexed articles and sources instead."
            ),
        )


class HTTPProvider(AIProvider):
    """Shared plumbing for HTTP-based providers.

    Uses urllib so the base install stays dependency-free. Network calls are
    refused outright unless ``ENCARTA_ALLOW_NETWORK`` is enabled, so an offline
    deployment cannot make an outbound request by accident.
    """

    endpoint: str = ""
    timeout: float = 45.0

    def __init__(self, config: Config) -> None:
        self.config = config
        self.model = config.ai_model or self.default_model

    default_model = ""

    @property
    def available(self) -> bool:
        return bool(self.config.api_key()) and self.config.allow_network

    def _post(self, url: str, payload: dict, headers: dict[str, str]) -> dict:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _guard(self) -> Completion | None:
        if not self.config.allow_network:
            return Completion("", self.model, False,
                              "Network access is disabled (ENCARTA_ALLOW_NETWORK=0).")
        if not self.config.api_key():
            return Completion("", self.model, False,
                              f"No API key configured for provider {self.name!r}.")
        return None


class AnthropicProvider(HTTPProvider):
    name = "anthropic"
    default_model = "claude-sonnet-5"
    endpoint = "https://api.anthropic.com/v1/messages"

    def complete(self, system: str, prompt: str, *, max_tokens: int = 900) -> Completion:
        blocked = self._guard()
        if blocked:
            return blocked
        try:
            data = self._post(
                self.endpoint,
                {
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
                {
                    "x-api-key": self.config.api_key() or "",
                    "anthropic-version": "2023-06-01",
                },
            )
            text = "".join(
                block.get("text", "") for block in data.get("content", [])
                if block.get("type") == "text"
            )
            return Completion(text.strip(), self.model)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
            log.warning("anthropic completion failed: %s", type(exc).__name__)
            return Completion("", self.model, False, f"Provider unreachable ({type(exc).__name__}).")


class OpenAIProvider(HTTPProvider):
    name = "openai"
    default_model = "gpt-4o-mini"
    endpoint = "https://api.openai.com/v1/chat/completions"

    def complete(self, system: str, prompt: str, *, max_tokens: int = 900) -> Completion:
        blocked = self._guard()
        if blocked:
            return blocked
        try:
            data = self._post(
                self.endpoint,
                {
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                },
                {"Authorization": f"Bearer {self.config.api_key()}"},
            )
            text = data["choices"][0]["message"]["content"]
            return Completion(text.strip(), self.model)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError) as exc:
            log.warning("openai completion failed: %s", type(exc).__name__)
            return Completion("", self.model, False, f"Provider unreachable ({type(exc).__name__}).")


class LocalProvider(HTTPProvider):
    """Talks to a local model server (Ollama-compatible).

    This is the offline AI path: it needs no API key and no internet, only a
    model running on the same machine.
    """

    name = "local"
    default_model = "llama3.1"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.endpoint = f"{config.local_ai_base_url.rstrip('/')}/api/chat"

    @property
    def available(self) -> bool:
        return True  # a local server needs no key and no internet

    def complete(self, system: str, prompt: str, *, max_tokens: int = 900) -> Completion:
        try:
            data = self._post(
                self.endpoint,
                {
                    "model": self.model,
                    "stream": False,
                    "options": {"num_predict": max_tokens},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                },
                {},
            )
            return Completion(data["message"]["content"].strip(), self.model)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
            return Completion(
                "", self.model, False,
                f"No local model server at {self.config.local_ai_base_url} "
                f"({type(exc).__name__}).",
            )


_PROVIDERS: dict[str, type[AIProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "local": LocalProvider,
}


def get_provider(config: Config) -> AIProvider:
    cls = _PROVIDERS.get(config.ai_provider)
    if cls is None:
        return NullProvider()
    return cls(config)  # type: ignore[call-arg]
