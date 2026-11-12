"""Read recipients from .xlsx / .xls / .csv and clean them up."""
from __future__ import annotations

import math
import re
from pathlib import Path

import pandas as pd
from email_validator import EmailNotValidError, validate_email


EXISTING_SEGMENTS = {"existing", "lapsed", "customer", "existing customer"}


class LoaderError(Exception):
    pass


def _norm(header: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(header).strip().lower())


def _clean(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def read_table(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise LoaderError(f"File not found: {path}")
    ext = path.suffix.lower()
    if ext == ".xlsx":
        return pd.read_excel(path, engine="openpyxl", dtype=str)
    if ext == ".xls":
        return pd.read_excel(path, engine="xlrd", dtype=str)
    if ext == ".csv":
        try:
            return pd.read_csv(path, dtype=str, encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(path, dtype=str, encoding="latin-1")
    raise LoaderError(f"Unsupported file type '{ext}'. Use .xlsx, .xls or .csv")


def map_columns(headers: list[str], aliases: dict[str, list[str]]) -> dict[str, str]:
    """Return {internal_field: original_header}."""
    lookup = {_norm(h): h for h in headers}
    mapping: dict[str, str] = {}
    for field_name, names in aliases.items():
        for alias in [field_name, *names]:
            hit = lookup.get(_norm(alias))
            if hit is not None and hit not in mapping.values():
                mapping[field_name] = hit
                break
    return mapping


def _first_name_from(full: str) -> str:
    full = full.strip()
    if not full:
        return ""
    first = full.split()[0]
    return first[:1].upper() + first[1:].lower() if first.isupper() or first.islower() else first


def load_recipients(path: str | Path, aliases: dict[str, list[str]],
                    check_dns: bool = False) -> tuple[list[dict], list[dict]]:
    """Return (valid_recipients, rejected_rows). Each rejected row has a 'reason'."""
    df = read_table(path)
    df = df.dropna(how="all")
    headers = [str(c) for c in df.columns]
    mapping = map_columns(headers, aliases)
    if "email" not in mapping:
        raise LoaderError(
            "Could not find an email column. Headers found: "
            + ", ".join(headers)
            + ". Rename one to 'email' or add an alias in config.yaml."
        )

    used_headers = set(mapping.values())
    seen: set[str] = set()
    valid, rejected = [], []

    for idx, row in df.iterrows():
        rec: dict = {k: _clean(row[h]) for k, h in mapping.items()}
        # keep any extra columns as AI context
        extras = {h: _clean(row[h]) for h in headers if h not in used_headers and _clean(row[h])}
        rec["extra"] = extras
        rec["row"] = int(idx) + 2  # spreadsheet row number (header is row 1)

        raw_email = rec.get("email", "")
        if not raw_email:
            rejected.append({**rec, "reason": "empty email"})
            continue
        try:
            info = validate_email(raw_email, check_deliverability=check_dns)
            email = info.normalized.lower()
        except EmailNotValidError as e:
            rejected.append({**rec, "reason": f"invalid email: {e}"})
            continue
        if email in seen:
            rejected.append({**rec, "reason": "duplicate"})
            continue
        seen.add(email)
        rec["email"] = email

        if not rec.get("first_name"):
            rec["first_name"] = _first_name_from(rec.get("full_name", ""))
        else:
            rec["first_name"] = _first_name_from(rec["first_name"])

        seg = rec.get("segment", "").strip().lower()
        if seg in EXISTING_SEGMENTS and rec.get("personal_link", "").startswith("http"):
            rec["segment"] = "existing"
        else:
            # DECISION: anyone not explicitly an existing customer with a real
            # personal link is treated as a new (cold) lead.
            rec["segment"] = "cold"
            rec["personal_link"] = ""

        for key in ("company", "industry", "city", "full_name"):
            rec.setdefault(key, "")
        valid.append(rec)

    return valid, rejected
