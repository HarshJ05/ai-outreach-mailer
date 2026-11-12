"""Write a personalized email per recipient.

Load balancing / failover:
  Gemini -> Grok -> plain template.
  A provider that hits a rate limit is put in "cooldown" and skipped
  until the cooldown ends, so traffic flows to the next provider.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, StrictUndefined
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import TEMPLATES_DIR
from .providers.base import LLMProvider, ProviderError, RateLimitError
from .validator import validate_email_content


@dataclass
class EmailDraft:
    subject: str
    body: str
    provider: str
    notes: list[str] = field(default_factory=list)


def parse_ai_json(raw: str) -> tuple[str, str]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ProviderError("AI output was not JSON")
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise ProviderError(f"AI output was not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ProviderError("AI output JSON is not an object")
    subject = str(data.get("subject", "")).strip()
    body = str(data.get("body", "")).strip().replace("\r\n", "\n")
    return subject, body


class Personalizer:
    def __init__(self, providers: list[LLMProvider], settings,
                 templates_dir: Path = TEMPLATES_DIR, clock=time.monotonic, sleep=time.sleep):
        self.providers = providers
        self.company = settings.company
        self.campaign = settings.campaign
        self.segments = settings.segments
        ai_cfg = settings.ai
        self.cooldown_seconds = ai_cfg.get("cooldown_seconds", 60)
        self.max_retries = max(1, int(ai_cfg.get("max_retries_per_provider", 2)))
        self.clock = clock
        self.sleep = sleep
        self._cooldown_until: dict[str, float] = {}
        self.prompt_template = (templates_dir / "base_prompt.txt").read_text(encoding="utf-8")
        self.jinja = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
        self.fallback = (templates_dir / "fallback.txt").read_text(encoding="utf-8")

    # ---------- shared pieces ----------
    @property
    def cta_line(self) -> str:
        c = self.campaign
        if c["discount_code"]:
            return f"Use code {c['discount_code']}: {c['cta_link']}"
        return f"Get started here: {c['cta_link']}"

    def existing_line(self, rec: dict) -> str:
        if rec.get("segment") != "existing" or not self.segments.get("existing_line"):
            return ""
        return self.segments["existing_line"].replace("{link}", rec.get("personal_link", ""))

    # ---------- prompt ----------
    def build_prompt(self, rec: dict) -> str:
        c = self.campaign
        public = {k: rec.get(k, "") for k in ("first_name", "full_name", "company", "industry", "city")}
        public = {k: v for k, v in public.items() if v}
        if rec.get("extra"):
            public["other_details"] = rec["extra"]

        optional = []
        if c["steps"]:
            optional.append(f"- Explain how it works: {c['steps']}")
        optional.append(f"- The offer: {c['offer']}")
        if c["bonus"]:
            optional.append(f"- Also mention: {c['bonus']}")
        if c["extra_instructions"]:
            optional.append(f"- {c['extra_instructions']}")

        existing = self.existing_line(rec)
        if existing:
            segment_rule = ("- This person is an existing customer. Include this line "
                            f"(you may rephrase lightly, keep the link exactly): {existing}")
        else:
            words = ", ".join(f'"{w}"' for w in self.segments.get("cold_forbidden_words") or [])
            segment_rule = ("- This person is a new lead. Do NOT say or imply they already have "
                            "an account with us or that anything about their account changed."
                            + (f" Never use these words: {words}." if words else ""))

        values = {
            "company_name": self.company["name"],
            "company_website": self.company["website"] or "",
            "what_we_do": self.company["what_we_do"] or "",
            "first_name": rec.get("first_name") or "there",
            "hook": c["hook"], "proof": c["proof"] or "a real customer's reported result",
            "optional_rules": "\n".join(optional),
            "cta_line": self.cta_line,
            "closing": c["closing"] or "Talk soon!",
            "segment_rule": segment_rule,
            "recipient_json": json.dumps(public, ensure_ascii=False),
        }
        # Only replace {simple_names}; leaves the JSON example braces alone.
        return re.sub(r"\{([a-z_]+)\}",
                      lambda m: str(values.get(m.group(1), m.group(0))),
                      self.prompt_template)

    # ---------- providers ----------
    def _available(self, p: LLMProvider) -> bool:
        return self.clock() >= self._cooldown_until.get(p.name, 0)

    def _call(self, p: LLMProvider, system_prompt: str, user_prompt: str) -> str:
        @retry(stop=stop_after_attempt(self.max_retries),
               wait=wait_exponential(multiplier=1, min=1, max=8),
               retry=retry_if_exception_type(ProviderError),
               sleep=self.sleep, reraise=True)
        def _do():
            return p.generate(system_prompt, user_prompt)
        return _do()

    def check(self, subject: str, body: str, rec: dict) -> list[str]:
        return validate_email_content(subject, body, rec, self.campaign,
                                      self.segments.get("cold_forbidden_words"))

    def write(self, rec: dict) -> EmailDraft:
        notes: list[str] = []
        prompt = self.build_prompt(rec)
        system_prompt = f"You are {self.company['name']}'s email copywriter. Reply with JSON only."
        for p in self.providers:
            if not self._available(p):
                notes.append(f"{p.name}: in cooldown, skipped")
                continue
            try:
                raw = self._call(p, system_prompt, prompt)
                subject, body = parse_ai_json(raw)
            except RateLimitError:
                self._cooldown_until[p.name] = self.clock() + self.cooldown_seconds
                notes.append(f"{p.name}: rate limited, cooling down {self.cooldown_seconds}s")
                continue
            except ProviderError as e:
                notes.append(f"{p.name}: failed ({str(e)[:120]})")
                continue
            problems = self.check(subject, body, rec)
            if problems:
                notes.append(f"{p.name}: rejected by validator ({'; '.join(problems)})")
                continue
            return EmailDraft(subject, body, p.name, notes)

        subject, body = self.render_fallback(rec)
        return EmailDraft(subject, body, "template", notes)

    # ---------- template fallback ----------
    def render_fallback(self, rec: dict) -> tuple[str, str]:
        tpl = self.jinja.from_string(self.fallback)
        text = tpl.render(**self.campaign,
                          first_name=rec.get("first_name") or "there",
                          recipient_company=rec.get("company", ""),
                          existing_line=self.existing_line(rec),
                          cta_line=self.cta_line)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        first, _, rest = text.partition("\n")
        subject = first.removeprefix("Subject:").strip()
        return subject, rest.strip()
