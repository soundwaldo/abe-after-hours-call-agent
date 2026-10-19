"""notify.py — send the lead summary to the owner by SMS via Twilio.

Uses the Twilio REST API directly (no twilio package needed).
"""
import os

import aiohttp
from loguru import logger


def _twilio_cfg():
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    from_number = os.getenv("TWILIO_PHONE_NUMBER", "")
    if not (sid and token and from_number):
        raise RuntimeError("Twilio SMS not configured (TWILIO_ACCOUNT_SID / "
                           "TWILIO_AUTH_TOKEN / TWILIO_PHONE_NUMBER)")
    return sid, token, from_number


async def send_sms(to_number: str, body: str) -> bool:
    """Send one SMS. Returns True on success. Never raises."""
    try:
        sid, token, from_number = _twilio_cfg()
    except RuntimeError as e:
        logger.error(str(e))
        return False
    url = (f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json")
    try:
        auth = aiohttp.BasicAuth(sid, token)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, auth=auth, data={
                "From": from_number,
                "To": to_number,
                "Body": body,
            }) as resp:
                if resp.status in (200, 201):
                    logger.info(f"Lead SMS sent to {to_number}")
                    return True
                text = await resp.text()
                logger.error(f"Twilio SMS failed ({resp.status}): {text[:200]}")
                return False
    except Exception as e:
        logger.error(f"Twilio SMS error: {e}")
        return False


async def send_lead_summary(lead, business_name: str) -> bool:
    """Format the lead and text it to the owner. Returns True if sent."""
    from .lead import format_sms
    to_number = os.getenv("OWNER_MOBILE", "")
    if not to_number:
        logger.error("OWNER_MOBILE not set - cannot send lead SMS")
        return False
    if not lead.is_worth_sending():
        logger.info("Call ended with no lead captured - nothing to send")
        return False
    return await send_sms(to_number, format_sms(lead, business_name))
