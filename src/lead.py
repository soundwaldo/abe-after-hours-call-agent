"""lead.py — the lead data model, phone normalization, and SMS formatting.

Pure logic, no network, no keys. Covered by tests/test_lead.py.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    PHX = ZoneInfo("America/Phoenix")
except Exception:  # pragma: no cover
    PHX = None


@dataclass
class Lead:
    name: str = ""
    callback_number: str = ""
    number_confirmed: bool = False
    company: str = ""
    need_type: str = ""          # repair | buy | rent | parts | other
    equipment: str = ""
    issue: str = ""
    urgency: str = ""           # down_now | safety | routine
    service_location: str = ""
    notes: str = ""
    # call metadata (filled by the server, not the LLM)
    call_sid: str = ""
    caller_number: str = ""
    started_at: str = ""

    def is_worth_sending(self):
        """Only text Clay when we actually captured someone to call back."""
        return bool(self.name.strip() or self.callback_number.strip())


def normalize_phone(raw: str) -> str:
    """Turn messy spoken digits into (602) 555-0134. Returns "" if unusable."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return ""
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


URGENCY_LABEL = {
    "down_now": "DOWN NOW",
    "safety": "SAFETY ISSUE",
    "routine": "routine",
}

NEED_LABEL = {
    "repair": "REPAIR",
    "buy": "BUY",
    "rent": "RENT",
    "parts": "PARTS",
    "other": "OTHER",
}


def _now_phx():
    if PHX:
        return datetime.now(PHX).strftime("%-I:%M %p")
    return datetime.now().strftime("%-I:%M %p")


def format_sms(lead: Lead, business_name: str) -> str:
    """One text message summarizing the call for the owner."""
    urgency = URGENCY_LABEL.get(lead.urgency, lead.urgency or "routine")
    need = NEED_LABEL.get(lead.need_type, (lead.need_type or "other").upper())
    num = normalize_phone(lead.callback_number) or lead.callback_number or "not captured"
    check = " confirmed" if lead.number_confirmed else ""

    lines = [
        f"{business_name} after-hours lead - {_now_phx()}",
        f"Name: {lead.name or 'not captured'}",
        f"Callback: {num}{check}",
        f"Need: {need}",
    ]
    if lead.company:
        lines.append(f"Company: {lead.company}")
    if lead.equipment:
        lines.append(f"Equipment: {lead.equipment}")
    if lead.issue:
        lines.append(f"Issue: {lead.issue}")
    lines.append(f"Urgency: {urgency}")
    if lead.service_location:
        lines.append(f"Location: {lead.service_location}")
    if lead.notes:
        lines.append(f"Notes: {lead.notes}")
    if not lead.name and not lead.callback_number and lead.caller_number:
        lines.append(f"(caller ID was {lead.caller_number} - no info captured)")
    return "\n".join(lines)
