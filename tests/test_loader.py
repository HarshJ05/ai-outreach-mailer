import pandas as pd
import pytest

from src.config import ConfigError, load_settings
from src.loader import LoaderError, load_recipients
from tests.conftest import ROOT


def test_example_xlsx(generic_settings):
    valid, rejected = load_recipients(ROOT / "data/recipients.example.xlsx", generic_settings.columns)
    emails = [r["email"] for r in valid]
    assert emails == ["aarav@example.com", "priya.nair@example.com", "rohan@example.com", "sneha@example.com"]
    reasons = {r["reason"].split(":")[0] for r in rejected}
    assert reasons == {"invalid email", "duplicate"}


def test_name_split_and_segments(generic_settings):
    valid, _ = load_recipients(ROOT / "data/recipients.example.xlsx", generic_settings.columns)
    by = {r["email"]: r for r in valid}
    assert by["aarav@example.com"]["first_name"] == "Aarav"
    assert by["rohan@example.com"]["segment"] == "existing"
    assert by["sneha@example.com"]["segment"] == "cold"
    assert by["aarav@example.com"]["extra"] == {"Notes": "Runs Instagram page"}


def test_csv_aliases_and_old_lapsed_columns(tmp_path, generic_settings):
    p = tmp_path / "r.csv"
    pd.DataFrame({"E-Mail": ["x@example.com", "y@example.com"], "full_name": ["MEERA patel", "Ravi"],
                  "Type": ["lapsed", "lapsed"],
                  "Reconnect Link": ["https://example.com/r/1", ""]}).to_csv(p, index=False)
    valid, _ = load_recipients(p, generic_settings.columns)
    assert valid[0]["first_name"] == "Meera"
    assert valid[0]["segment"] == "existing"      # old "lapsed" + reconnect link still works
    assert valid[1]["segment"] == "cold"          # no link -> treated as a new lead


def test_csv_non_utf8(tmp_path, generic_settings):
    p = tmp_path / "r.csv"
    p.write_bytes("email,name\nz@example.com,Jos\xe9\n".encode("latin-1"))
    valid, _ = load_recipients(p, generic_settings.columns)
    assert valid[0]["first_name"] == "José"


def test_missing_email_column(tmp_path, generic_settings):
    p = tmp_path / "r.csv"
    pd.DataFrame({"Name": ["A"], "Phone": ["1"]}).to_csv(p, index=False)
    with pytest.raises(LoaderError, match="Headers found: Name, Phone"):
        load_recipients(p, generic_settings.columns)


def test_config_requires_core_fields(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("company: {name: X}\ncampaign: {hook: hi}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="campaign.offer, campaign.cta_link"):
        load_settings(p)
