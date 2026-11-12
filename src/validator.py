"""Safety checks on every email before it can be sent."""
from __future__ import annotations

import re

PLACEHOLDER_RE = re.compile(
    r"\[[^\]]*(?:name|link|company)[^\]]*\]|\{\{|\}\}|\{[a-z_]+\}|<name>", re.I)

# Money amounts: ₹10K, Rs. 2,000, INR 500, $49, USD 1.5M, €20, £9.99, ₹1.4L, ₹2 crore
MONEY_RE = re.compile(
    r"(?:[₹$€£]\s?|\b(?:Rs\.?|INR|USD|EUR|GBP)\s?)\d[\d,]*(?:\.\d+)?"
    r"(?:\s?(?:k|l|lakhs?|cr|crores?|m|mn|million|bn|billion)\b)?",
    re.I,
)
_PREFIX = {"rs": "₹", "rs.": "₹", "inr": "₹", "usd": "$", "eur": "€", "gbp": "£"}

BANNED_WORDS = ["guaranteed", "guarantee", "100%", "risk-free", "risk free"]

# campaign fields whose amounts are approved for use in emails
AMOUNT_SOURCES = ("subject", "hook", "proof", "steps", "offer", "bonus", "closing")


def _norm_amount(s: str) -> str:
    s = s.strip()
    m = re.match(r"(rs\.?|inr|usd|eur|gbp)", s, re.I)
    if m:
        s = _PREFIX[m.group(1).lower()] + s[m.end():]
    return re.sub(r"[\s,]+", "", s).lower()


def approved_amounts(campaign: dict) -> set[str]:
    text = " ".join(str(campaign.get(k, "")) for k in AMOUNT_SOURCES)
    return {_norm_amount(a) for a in MONEY_RE.findall(text)}


def validate_email_content(subject: str, body: str, recipient: dict, campaign: dict,
                           cold_forbidden: list[str] | None = None) -> list[str]:
    """Return a list of problems. Empty list = OK to send."""
    problems: list[str] = []
    subject = (subject or "").strip()
    body = (body or "").strip()
    text = f"{subject}\n{body}"
    low = text.lower()

    if not subject:
        problems.append("subject is empty")
    elif len(subject) > 80:
        problems.append(f"subject too long ({len(subject)} chars)")
    if len(body) < 150:
        problems.append(f"body too short ({len(body)} chars)")
    elif len(body) > 1800:
        problems.append(f"body too long ({len(body)} chars)")

    if campaign.get("cta_link") and campaign["cta_link"] not in body:
        problems.append("call-to-action link missing")
    if campaign.get("discount_code") and campaign["discount_code"] not in body:
        problems.append("discount code missing")

    if PLACEHOLDER_RE.search(text):
        problems.append("leftover placeholder found")

    first = recipient.get("first_name", "")
    if first and first.lower() not in body.lower():
        problems.append("recipient's first name not used")

    for w in BANNED_WORDS:
        if w in low:
            problems.append(f"banned word: '{w}'")

    if recipient.get("segment", "cold") == "cold":
        for w in cold_forbidden or []:
            if w and w.lower() in low:
                problems.append(f"cold lead email mentions '{w}'")
    else:
        link = recipient.get("personal_link", "")
        if link and link not in body:
            problems.append("personal link missing for existing customer")

    allowed = approved_amounts(campaign)
    for amt in MONEY_RE.findall(text):
        if _norm_amount(amt) not in allowed:
            problems.append(f"unapproved amount '{amt.strip()}'")

    return problems
