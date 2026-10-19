"""server.py — FastAPI front door for the voice agent.

  POST /voice  Twilio webhook: returns TwiML that streams call audio to /ws
  WS   /ws     Twilio Media Stream -> Pipecat pipeline (one bot per call)
  GET  /health liveness check

Run:  uvicorn src.server:app --host 0.0.0.0 --port 7860
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from loguru import logger
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from .bot import run_bot
from .dashboard import dashboard_page, lead_update_api, pipeline_api, stats_api
from .lead import Lead
from .notify import send_lead_summary
from .persona import load_business
from .store import classify_outcome, log_call_end, log_call_start

load_dotenv(override=True)

app = FastAPI(title="ABE After-Hours Call Agent")
business = load_business()
BUSINESS_NAME = business["business"]["name"]


@app.get("/health")
async def health():
    return {"ok": True, "business": BUSINESS_NAME}


app.get("/dashboard")(dashboard_page)
app.get("/api/stats")(stats_api)
app.get("/api/pipeline")(pipeline_api)
app.patch("/api/leads/{lead_id}")(lead_update_api)


@app.post("/voice")
async def voice():
    """Twilio calls this when the number rings. Hand the audio to the bot."""
    host = os.getenv("PUBLIC_HOST", "").strip()
    if not host:
        logger.error("PUBLIC_HOST not set - Twilio cannot reach /ws")
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "  <Connect>\n"
        f'    <Stream url="wss://{host}/ws" />\n'
        "  </Connect>\n"
        "</Response>"
    )
    return PlainTextResponse(twiml, media_type="application/xml")


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    try:
        transport_type, call_data = await parse_telephony_websocket(websocket)
        logger.info(f"Incoming {transport_type} call: "
                    f"{call_data.get('call_id', '?')}")
    except Exception as e:
        logger.error(f"Could not parse telephony handshake: {e}")
        await websocket.close()
        return

    serializer = TwilioFrameSerializer(
        stream_sid=call_data["stream_id"],
        call_sid=call_data["call_id"],
        account_sid=os.getenv("TWILIO_ACCOUNT_SID"),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN"),
    )
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    lead = Lead()
    call_sid = call_data.get("call_id", "")
    caller = call_data.get("caller_number", "") or call_data.get("from", "")
    call_id = log_call_start(call_sid, caller)
    try:
        await run_bot(transport, business, lead, call_data)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected by Twilio")
    except Exception as e:
        logger.error(f"Bot error: {e}")

    outcome = classify_outcome(lead)
    sms_sent = False
    if lead.is_worth_sending():
        sms_sent = await send_lead_summary(lead, BUSINESS_NAME)
    if call_id:
        log_call_end(call_id, outcome, sms_sent,
                     lead if outcome != "hangup_early" else None)
