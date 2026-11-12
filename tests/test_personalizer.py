import json

from src.personalizer import Personalizer, parse_ai_json
from src.providers.base import LLMProvider, ProviderError, RateLimitError
from tests.test_validator import good_body


class FakeProvider(LLMProvider):
    def __init__(self, name, behaviour):
        self.name = name
        self.behaviour = behaviour  # callable or exception instance
        self.calls = 0

    def generate(self, system_prompt, user_prompt):
        self.calls += 1
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return self.behaviour(user_prompt)


def ok(campaign, name="Aarav"):
    return lambda _prompt: json.dumps({"subject": campaign["subject"], "body": good_body(campaign, name)})


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make(providers, settings, clock=None):
    return Personalizer(providers, settings, clock=clock or Clock(), sleep=lambda s: None)


def test_gemini_first(settings, cold_rec):
    g, x = FakeProvider("gemini", ok(settings.campaign)), FakeProvider("grok", ok(settings.campaign))
    d = make([g, x], settings).write(cold_rec)
    assert d.provider == "gemini" and x.calls == 0


def test_rate_limit_falls_to_grok_and_cools_down(settings, cold_rec):
    clock = Clock()
    g = FakeProvider("gemini", RateLimitError("429"))
    x = FakeProvider("grok", ok(settings.campaign))
    p = make([g, x], settings, clock)
    assert p.write(cold_rec).provider == "grok"
    assert p.write(cold_rec).provider == "grok"
    assert g.calls == 1  # second email skipped gemini (cooldown)
    clock.t += settings.ai["cooldown_seconds"] + 1
    p.write(cold_rec)
    assert g.calls == 2  # cooldown over, gemini tried again


def test_errors_retry_then_template(settings, cold_rec):
    g = FakeProvider("gemini", ProviderError("boom"))
    x = FakeProvider("grok", ProviderError("boom"))
    d = make([g, x], settings).write(cold_rec)
    assert d.provider == "template"
    assert g.calls == settings.ai["max_retries_per_provider"]
    assert "Aarav" in d.body


def test_validator_rejection_moves_on(settings, cold_rec):
    bad = lambda _p: json.dumps({"subject": "Hi", "body": "too short"})
    g, x = FakeProvider("gemini", bad), FakeProvider("grok", ok(settings.campaign))
    assert make([g, x], settings).write(cold_rec).provider == "grok"


def test_prompt_is_built_from_config(settings, cold_rec, existing_rec):
    p = make([], settings)
    cold = p.build_prompt(cold_rec)
    assert "Do NOT say or imply" in cold
    assert settings.company["name"] in cold and settings.campaign["hook"] in cold
    assert settings.campaign["cta_link"] in cold
    assert '{"subject": "...", "body": "..."}' in cold
    assert not __import__("re").search(r"\{[a-z_]+\}", cold)   # every placeholder filled
    assert existing_rec["personal_link"] in p.build_prompt(existing_rec)


def test_generic_config_has_no_preset_brand(generic_settings, cold_rec):
    p = make([], generic_settings)
    assert "northwind" not in p.build_prompt(cold_rec).lower()
    subject, body = p.render_fallback(cold_rec)
    assert "northwind" not in (subject + body).lower()


def test_parse_json_with_fences():
    s, b = parse_ai_json('```json\n{"subject":"a","body":"b"}\n```')
    assert (s, b) == ("a", "b")
