from .base import LLMProvider, ProviderError, RateLimitError


def build_providers(settings) -> tuple[list[LLMProvider], list[str]]:
    """Create providers in configured order. Returns (providers, warnings)."""
    from .gemini import GeminiProvider
    from .grok import GrokProvider

    ai = settings.ai
    temp = ai.get("temperature", 0.7)
    timeout = ai.get("timeout_seconds", 40)
    factories = {
        "gemini": lambda: GeminiProvider(settings.env_get("GEMINI_API_KEY"),
                                         ai.get("gemini_model", "gemini-flash-latest"), temp, timeout),
        "grok": lambda: GrokProvider(settings.env_get("XAI_API_KEY"),
                                     ai.get("grok_model", "grok-4-latest"), temp, timeout),
    }
    providers, warnings = [], []
    for name in ai.get("provider_order", ["gemini", "grok"]):
        factory = factories.get(name)
        if not factory:
            warnings.append(f"Unknown provider '{name}' in config, skipped")
            continue
        try:
            providers.append(factory())
        except ProviderError as e:
            warnings.append(f"{name} disabled: {e}")
    return providers, warnings


__all__ = ["LLMProvider", "ProviderError", "RateLimitError", "build_providers"]
