from src.personalizer import Personalizer
from src.validator import approved_amounts, validate_email_content


def good_body(c, name="Aarav", extra=""):
    code_line = (f"Use code {c['discount_code']}: {c['cta_link']}" if c["discount_code"]
                 else f"Get started here: {c['cta_link']}")
    return (f"Hi {name},\n\n{c['hook']}\n{c['proof']}\n\n"
            f"Here's how it works: {c['steps']}.\n\n"
            f"{extra}{c['offer']}\n\n{code_line}\n\n{c['closing']}")


def check(settings, subject, body, rec):
    return validate_email_content(subject, body, rec, settings.campaign,
                                  settings.segments["cold_forbidden_words"])


def test_good_email_passes(settings, cold_rec):
    assert check(settings, settings.campaign["subject"], good_body(settings.campaign), cold_rec) == []


def test_missing_link(settings, cold_rec):
    body = good_body(settings.campaign).replace(settings.campaign["cta_link"], "")
    assert "call-to-action link missing" in check(settings, "Hi", body, cold_rec)


def test_placeholder(settings, cold_rec):
    body = good_body(settings.campaign, name="[first name]")
    assert "leftover placeholder found" in check(settings, "Hi", body, cold_rec)


def test_invented_amount(settings, cold_rec):
    for fake in ("Another client made ₹5L last week.", "Others made Rs. 50,000.", "Worth $999."):
        body = good_body(settings.campaign, extra=fake + "\n\n")
        assert any("unapproved amount" in p for p in check(settings, "Hi", body, cold_rec)), fake


def test_words_ending_in_rs_are_not_money(settings, cold_rec):
    body = good_body(settings.campaign, extra="Our partners 24 hours a day, years 3 running.\n\n")
    assert not any("unapproved" in p for p in check(settings, "Hi", body, cold_rec))


def test_amounts_come_from_config(generic_settings):
    amounts = approved_amounts(generic_settings.campaign)
    assert {"₹10k", "₹1.4l", "₹2000", "₹4999"} <= amounts


def test_cold_cannot_say_disconnected(settings, cold_rec):
    body = good_body(settings.campaign, extra="Your account got disconnected.\n\n")
    assert any("disconnected" in p for p in check(settings, "Hi", body, cold_rec))


def test_existing_needs_personal_link(settings, existing_rec):
    body = good_body(settings.campaign, name="Rohan")
    assert "personal link missing for existing customer" in check(settings, "Hi", body, existing_rec)


def test_fallback_template_passes_validator(settings, cold_rec, existing_rec):
    p = Personalizer([], settings)
    for rec in (cold_rec, existing_rec):
        subject, body = p.render_fallback(rec)
        assert p.check(subject, body, rec) == [], body
    _, body = p.render_fallback(existing_rec)
    assert existing_rec["personal_link"] in body
    _, body = p.render_fallback(cold_rec)
    assert "disconnected" not in body and "Sharma Sweets" in body
