from __future__ import annotations

from .base import LLMProvider, ProviderError, RateLimitError


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, temperature: float = 0.7, timeout: int = 40):
        if not api_key:
            raise ProviderError("GEMINI_API_KEY is not set")
        from google import genai  # imported lazily so tests don't need it
        from google.genai import types

        self._types = types
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=timeout * 1000),
        )
        self.model = model
        self.temperature = temperature

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=self._types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=self.temperature,
                    response_mime_type="application/json",
                ),
            )
        except Exception as e:  # SDK raises several error types
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            msg = str(e)
            if code == 429 or "RESOURCE_EXHAUSTED" in msg or "429" in msg:
                raise RateLimitError(msg) from e
            raise ProviderError(msg) from e
        text = (resp.text or "").strip()
        if not text:
            raise ProviderError("Gemini returned an empty response")
        return text

    def list_models(self) -> list[str]:
        return [m.name for m in self.client.models.list()]
