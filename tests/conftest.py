import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import load_settings  # noqa: E402


@pytest.fixture(params=["config.yaml", "examples/northwind-ads.yaml"], ids=["generic", "preset"])
def settings(request):
    s = load_settings(ROOT / request.param)
    s.env.update({"FROM_EMAIL": "hello@example.com", "UNSUBSCRIBE_EMAIL": "hello@example.com",
                  "COMPANY_ADDRESS": "Example Co, Test Address", "FROM_NAME": ""})
    return s


@pytest.fixture
def generic_settings():
    return load_settings(ROOT / "config.yaml")


@pytest.fixture
def campaign(settings):
    return settings.campaign


@pytest.fixture
def cold_rec():
    return {"email": "aarav@example.com", "first_name": "Aarav", "company": "Sharma Sweets",
            "industry": "Bakery", "city": "Jaipur", "segment": "cold", "personal_link": "", "extra": {}}


@pytest.fixture
def existing_rec():
    return {"email": "rohan@example.com", "first_name": "Rohan", "company": "FitZone",
            "industry": "Fitness", "city": "Noida", "segment": "existing",
            "personal_link": "https://example.com/reconnect?u=x", "extra": {}}
