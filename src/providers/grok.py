from __future__ import annotations

from .base import LLMProvider, ProviderError, RateLimitError

XAI_BASE_URL = "https://api.x.ai/v1"


class GrokProvider(LLMProvider):
    """xAI Grok via its OpenAI-compatible API."""
    name = "grok"

    def __init__(self, api_key: str, model: str, temperature: float = 0.7, timeout: int = 40):
        if not api_key:
            raise ProviderError("XAI_API_KEY is not set")
        import openai

        self._openai = openai
        self.client = openai.OpenAI(api_key=api_key, base_url=XAI_BASE_URL,
                                    timeout=timeout, max_retries=0)
        self.model = model
        self.temperature = temperature

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except self._openai.RateLimitError as e:
            raise RateLimitError(str(e)) from e
        except Exception as e:
            raise ProviderError(str(e)) from e
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            raise ProviderError("Grok returned an empty response")
        return text

    def list_models(self) -> list[str]:
        return [m.id for m in self.client.models.list()]
