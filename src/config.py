"""Loads config.yaml and .env into one settings object."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"
LOGS_DIR = ROOT / "logs"

CAMPAIGN_DEFAULTS = {
    "name": "default", "subject": "", "hook": "", "proof": "", "steps": "", "offer": "",
    "bonus": "", "discount_code": "", "cta_link": "", "closing": "", "extra_instructions": "",
}
COMPANY_DEFAULTS = {"name": "", "website": "", "what_we_do": "", "sender_name": "", "sender_title": ""}
SEGMENT_DEFAULTS = {"existing_line": "", "cold_forbidden_words": []}


class ConfigError(Exception):
    pass


@dataclass
class Settings:
    company: dict
    campaign: dict
    segments: dict
    ai: dict
    sending: dict
    columns: dict
    env: dict = field(default_factory=dict)

    def env_get(self, key: str, default: str = "") -> str:
        return self.env.get(key, default) or default


ENV_KEYS = [
    "GEMINI_API_KEY", "XAI_API_KEY",
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_SECURITY",
    "FROM_NAME", "FROM_EMAIL", "REPLY_TO",
    "COMPANY_ADDRESS", "UNSUBSCRIBE_EMAIL",
]


def _str_values(d: dict) -> dict:
    return {k: ("" if v is None else v if isinstance(v, (list, dict)) else str(v).strip())
            for k, v in d.items()}


def load_settings(config_path: str | Path | None = None) -> Settings:
    load_dotenv(ROOT / ".env")
    path = Path(config_path) if config_path else ROOT / "config.yaml"
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    company = _str_values({**COMPANY_DEFAULTS, **(raw.get("company") or {})})
    campaign = _str_values({**CAMPAIGN_DEFAULTS, **(raw.get("campaign") or {})})
    segments = {**SEGMENT_DEFAULTS, **(raw.get("segments") or {})}

    missing = [f"company.{k}" for k in ("name",) if not company[k]]
    missing += [f"campaign.{k}" for k in ("hook", "offer", "cta_link") if not campaign[k]]
    if missing:
        raise ConfigError(f"{path.name} is missing required values: {', '.join(missing)}")
    if not campaign["subject"]:
        campaign["subject"] = campaign["hook"][:70]

    env = {k: os.getenv(k, "").strip() for k in ENV_KEYS}
    return Settings(company=company, campaign=campaign, segments=segments,
                    ai=raw.get("ai") or {}, sending=raw.get("sending") or {},
                    columns=raw.get("columns") or {}, env=env)
