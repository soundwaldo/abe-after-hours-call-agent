"""Tests for the pure lead logic (no network, no keys needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lead import Lead, format_sms, normalize_phone


def test_normalize_phone():
    assert normalize_phone("6025550134") == "(602) 555-0134"
    assert normalize_phone("16025550134") == "(602) 555-0134"
    assert normalize_phone("(602) 555-0134") == "(602) 555-0134"
    assert normalize_phone("602-555-0134") == "(602) 555-0134"
    assert normalize_phone("5550134") == ""
    assert normalize_phone("") == ""
    assert normalize_phone("not a number") == ""


def test_lead_worth_sending():
    assert Lead(name="Juan").is_worth_sending()
    assert Lead(callback_number="6025550134").is_worth_sending()
    assert not Lead().is_worth_sending()
    assert not Lead(company="Acme").is_worth_sending()


def test_format_sms_full():
    lead = Lead(
        name="Juan Perez",
        callback_number="6025550134",
        number_confirmed=True,
        company="Acme Warehousing",
        need_type="repair",
        equipment="Toyota 5k sit-down",
        issue="won't start, just clicks",
        urgency="down_now",
        service_location="1234 W Buckeye Rd, Phoenix",
        notes="needs it by morning shift",
        caller_number="+16025559999",
    )
    sms = format_sms(lead, "Arizona's Best Equipment")
    assert "Juan Perez" in sms
    assert "(602) 555-0134 confirmed" in sms
    assert "REPAIR" in sms
    assert "DOWN NOW" in sms
    assert "Acme Warehousing" in sms
    assert "1234 W Buckeye Rd" in sms


def test_format_sms_minimal():
    lead = Lead(name="Maria", callback_number="4805550100")
    sms = format_sms(lead, "Arizona's Best Equipment")
    assert "Maria" in sms
    assert "(480) 555-0100" in sms
    assert "routine" in sms
    assert "Company" not in sms  # optional fields omitted when empty
