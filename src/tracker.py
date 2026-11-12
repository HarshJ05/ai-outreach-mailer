"""Sent log + unsubscribe list, so re-runs never double-send."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .config import LOGS_DIR

FIELDS = ["timestamp", "campaign", "email", "status", "provider", "subject", "error"]


class Tracker:
    def __init__(self, logs_dir: Path = LOGS_DIR):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.sent_log = self.logs_dir / "sent_log.csv"
        self.unsub_file = self.logs_dir / "unsubscribed.txt"
        self._sent: set[tuple[str, str]] = set()
        self._today_count = 0
        self._unsub: set[str] = set()
        self._load()

    def _load(self):
        today = datetime.now().date().isoformat()
        if self.sent_log.exists():
            with open(self.sent_log, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    if row.get("status") == "sent":
                        self._sent.add((row["campaign"], row["email"].lower()))
                        if row.get("timestamp", "").startswith(today):
                            self._today_count += 1
        if self.unsub_file.exists():
            self._unsub = {l.strip().lower() for l in self.unsub_file.read_text(encoding="utf-8-sig").splitlines()
                           if l.strip() and not l.startswith("#")}

    def already_sent(self, email: str, campaign: str) -> bool:
        return (campaign, email.lower()) in self._sent

    def is_unsubscribed(self, email: str) -> bool:
        return email.lower() in self._unsub

    @property
    def sent_today(self) -> int:
        return self._today_count

    def add_unsubscribe(self, email: str):
        email = email.strip().lower()
        if email and email not in self._unsub:
            with open(self.unsub_file, "a", encoding="utf-8") as f:
                f.write(email + "\n")
            self._unsub.add(email)

    def log(self, *, campaign: str, email: str, status: str, provider: str = "",
            subject: str = "", error: str = ""):
        new = not self.sent_log.exists()
        with open(self.sent_log, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow({"timestamp": datetime.now().isoformat(timespec="seconds"),
                        "campaign": campaign, "email": email, "status": status,
                        "provider": provider, "subject": subject, "error": error[:300]})
        if status == "sent":
            self._sent.add((campaign, email.lower()))
            self._today_count += 1
