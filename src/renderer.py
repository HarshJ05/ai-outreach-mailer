"""Turn subject + body into a real email (plain text + HTML + headers)."""
from __future__ import annotations

import re
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, formatdate

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from .config import TEMPLATES_DIR

URL_RE = re.compile(r"(https?://[^\s<>\"]+[^\s<>\".,;:!?)])")

_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)),
                   autoescape=select_autoescape(["html", "j2"]))


def _para_html(text: str) -> Markup:
    safe = str(escape(text))
    safe = URL_RE.sub(r'<a href="\1" style="color:#2f6fed;">\1</a>', safe)
    return Markup(safe.replace("\n", "<br>"))


def build_message(*, to_email: str, subject: str, body: str, settings) -> EmailMessage:
    c = settings.company
    unsub = settings.env_get("UNSUBSCRIBE_EMAIL") or settings.env_get("FROM_EMAIL")
    address = settings.env_get("COMPANY_ADDRESS")
    from_email = settings.env_get("FROM_EMAIL") or settings.env_get("SMTP_USER")
    from_name = settings.env_get("FROM_NAME") or c.get("name") or ""
    # DECISION: dry runs work without .env; real sends need SMTP_USER anyway.
    from_email = from_email or "sender-not-configured@example.com"

    signature = f"{c.get('sender_name', '')}\n{c.get('sender_title', '')}".strip()
    footer = f"Don't want these emails? Reply \"unsubscribe\" or write to {unsub}."
    if address:
        footer += f"\n{address}"
    text = f"{body.strip()}\n\n{signature}\n\n--\n{footer}\n"

    paragraphs = [_para_html(p.strip()) for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    html = _env.get_template("email.html.j2").render(
        subject=subject, paragraphs=paragraphs,
        sender_name=c.get("sender_name", ""), sender_title=c.get("sender_title", ""),
        unsubscribe_email=unsub, company_address=address,
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to_email
    if settings.env_get("REPLY_TO"):
        msg["Reply-To"] = settings.env_get("REPLY_TO")
    msg["Date"] = formatdate(localtime=True)
    domain = from_email.split("@")[-1] if "@" in from_email else None
    msg["Message-ID"] = make_msgid(domain=domain)
    if unsub:
        msg["List-Unsubscribe"] = f"<mailto:{unsub}?subject=unsubscribe>"
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg
