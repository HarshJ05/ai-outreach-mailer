"""Email delivery. SMTP today; add an API sender (Brevo/SES/Resend) by
subclassing BaseSender and wiring it in build_sender()."""
from __future__ import annotations

import random
import smtplib
import ssl
import time
from email.message import EmailMessage


class PermanentSendError(Exception):
    """Do not retry (bad address, rejected, auth failure)."""


class TemporarySendError(Exception):
    """Worth retrying (4xx, connection drop)."""


class BaseSender:
    def send(self, msg: EmailMessage) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SMTPSender(BaseSender):
    def __init__(self, host: str, port: int, user: str, password: str, timeout: int = 30,
                 security: str = ""):
        if not (host and user and password):
            raise PermanentSendError("SMTP_HOST, SMTP_USER and SMTP_PASSWORD must be set in .env")
        self.host, self.port, self.user, self.password = host, int(port), user, password
        self.timeout = timeout
        # "starttls" (port 587), "ssl" (port 465) or "none" (local testing only)
        self.security = (security or ("ssl" if self.port == 465 else "starttls")).lower()
        self._conn: smtplib.SMTP | None = None

    def _connect(self):
        ctx = ssl.create_default_context()
        if self.security == "ssl":
            conn = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=ctx)
        else:
            conn = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            conn.ehlo()
            if self.security == "starttls":
                conn.starttls(context=ctx)
                conn.ehlo()
        try:
            conn.login(self.user, self.password)
        except smtplib.SMTPAuthenticationError as e:
            raise PermanentSendError(
                "SMTP login failed. For Gmail/Workspace use an App Password, not the normal password."
            ) from e
        self._conn = conn

    def verify(self):
        """Log in once to check credentials."""
        self._connect()

    def send(self, msg: EmailMessage) -> None:
        try:
            if self._conn is None:
                self._connect()
            self._conn.send_message(msg)
        except smtplib.SMTPRecipientsRefused as e:
            raise PermanentSendError(f"recipient refused: {e.recipients}") from e
        except smtplib.SMTPResponseException as e:
            self._conn = None if e.smtp_code in (421,) else self._conn
            if 400 <= e.smtp_code < 500:
                raise TemporarySendError(f"{e.smtp_code} {e.smtp_error!r}") from e
            raise PermanentSendError(f"{e.smtp_code} {e.smtp_error!r}") from e
        except (smtplib.SMTPServerDisconnected, ConnectionError, TimeoutError, OSError) as e:
            self._conn = None
            raise TemporarySendError(str(e)) from e

    def close(self):
        if self._conn:
            try:
                self._conn.quit()
            except Exception:
                pass
            self._conn = None


class Throttle:
    """Keeps sending under N emails/minute plus random jitter."""

    def __init__(self, per_minute: int, jitter: tuple[float, float] = (0, 0), sleep=time.sleep,
                 clock=time.monotonic):
        self.interval = 60.0 / max(1, per_minute)
        self.jitter = jitter
        self.sleep, self.clock = sleep, clock
        self._last: float | None = None

    def wait(self):
        if self._last is not None:
            target = self.interval + random.uniform(*self.jitter)
            elapsed = self.clock() - self._last
            if elapsed < target:
                self.sleep(target - elapsed)
        self._last = self.clock()


def send_with_retry(sender: BaseSender, msg: EmailMessage, max_retries: int = 3, sleep=time.sleep):
    attempt = 0
    while True:
        attempt += 1
        try:
            sender.send(msg)
            return
        except TemporarySendError:
            if attempt >= max_retries:
                raise
            sleep(min(30, 2 ** attempt))


def build_sender(settings) -> BaseSender:
    e = settings.env_get
    return SMTPSender(e("SMTP_HOST"), int(e("SMTP_PORT", "587")), e("SMTP_USER"), e("SMTP_PASSWORD"),
                      security=e("SMTP_SECURITY"))
