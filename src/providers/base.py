from __future__ import annotations

from abc import ABC, abstractmethod


class RateLimitError(Exception):
    """Provider said 'too many requests' (HTTP 429 / quota)."""


class ProviderError(Exception):
    """Any other provider failure (network, 5xx, bad key, bad output)."""


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Return raw text (expected to be JSON with subject + body)."""

    def list_models(self) -> list[str]:
        return []
