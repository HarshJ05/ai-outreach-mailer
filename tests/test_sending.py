from src.renderer import build_message
from src.sender import BaseSender, TemporarySendError, send_with_retry
from src.tracker import Tracker


def test_message_has_footer_and_unsubscribe(settings):
    msg = build_message(to_email="a@example.com", subject="Hello",
                        body="Hi A,\n\nUse code X: https://example.com/#pricing", settings=settings)
    assert msg["List-Unsubscribe"] == "<mailto:hello@example.com?subject=unsubscribe>"
    assert settings.company["name"] in msg["From"]          # FROM_NAME empty -> company name
    text = msg.get_body(("plain",)).get_content()
    html = msg.get_body(("html",)).get_content()
    assert settings.company["sender_name"] in text and "unsubscribe" in text
    assert '<a href="https://example.com/#pricing"' in html


def test_tracker_skips_already_sent(tmp_path):
    t = Tracker(tmp_path)
    t.log(campaign="c1", email="A@x.com", status="sent")
    t2 = Tracker(tmp_path)  # fresh load from disk, like a re-run
    assert t2.already_sent("a@x.com", "c1")
    assert not t2.already_sent("a@x.com", "c2")
    assert t2.sent_today == 1
    t2.add_unsubscribe("B@x.com")
    assert Tracker(tmp_path).is_unsubscribed("b@x.com")


def test_retry_on_temporary_error():
    class Flaky(BaseSender):
        n = 0

        def send(self, msg):
            self.n += 1
            if self.n < 3:
                raise TemporarySendError("421")

    s = Flaky()
    send_with_retry(s, None, max_retries=3, sleep=lambda x: None)
    assert s.n == 3


def test_bad_password_gives_clear_error(monkeypatch):
    import smtplib

    import pytest

    from src.sender import PermanentSendError, SMTPSender

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def ehlo(self): pass
        def starttls(self, **k): pass
        def login(self, u, p): raise smtplib.SMTPAuthenticationError(535, b"bad creds")

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    with pytest.raises(PermanentSendError, match="App Password"):
        SMTPSender("smtp.gmail.com", 587, "a@b.com", "x").verify()
