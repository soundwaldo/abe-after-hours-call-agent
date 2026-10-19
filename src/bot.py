"""bot.py — the Pipecat voice pipeline for one call.

Transport (Twilio media stream) -> Deepgram STT -> Groq LLM -> Deepgram TTS.

The LLM has two function tools:
  - record_lead: save/update the caller's lead as info comes in
  - end_call: hang up after the closing line is delivered

When the call ends, run_bot() returns the Lead for the server to SMS.
"""
import os

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import EndFrame, LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport

from .lead import Lead, normalize_phone
from .persona import build_system_prompt

# Groq exposes an OpenAI-compatible API; Pipecat's OpenAI service can point at it.
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"


def _record_lead_schema():
    return FunctionSchema(
        name="record_lead",
        description=(
            "Save the caller's lead information. Call it as soon as you have "
            "the name and callback number, and again if any detail changes."
        ),
        properties={
            "name": {"type": "string", "description": "Caller's full name"},
            "callback_number": {
                "type": "string",
                "description": "Callback phone number, digits only",
            },
            "number_confirmed": {
                "type": "boolean",
                "description": "True only after reading the number back and the caller confirms",
            },
            "company": {"type": "string", "description": "Caller's company, if given"},
            "need_type": {
                "type": "string",
                "enum": ["repair", "buy", "rent", "parts", "other"],
            },
            "equipment": {"type": "string", "description": "Equipment type/make/capacity"},
            "issue": {"type": "string", "description": "Problem or need described"},
            "urgency": {
                "type": "string",
                "enum": ["down_now", "safety", "routine"],
                "description": "down_now if equipment is down now, safety if anyone could get hurt",
            },
            "service_location": {"type": "string", "description": "Where the equipment is"},
            "notes": {"type": "string", "description": "Anything else worth passing on"},
        },
        required=["name", "callback_number", "need_type"],
    )


def _end_call_schema():
    return FunctionSchema(
        name="end_call",
        description=(
            "End the phone call. Call it only after you have said the closing "
            "line and recorded the lead."
        ),
        properties={},
        required=[],
    )


async def run_bot(transport: BaseTransport, business: dict, lead: Lead,
                 call_data=None) -> Lead:
    """Run the voice pipeline for one call, filling in lead. Returns the lead."""
    if call_data:
        try:
            lead.call_sid = call_data.get("call_id", "") or ""
            lead.caller_number = call_data.get("from_number", "") or ""
        except Exception:
            pass

    groq_key = os.getenv("GROQ_API_KEY", "")
    deepgram_key = os.getenv("DEEPGRAM_API_KEY", "")
    if not groq_key or not deepgram_key:
        raise RuntimeError("GROQ_API_KEY and DEEPGRAM_API_KEY must be set")

    voice = business["agent"].get("voice", "aura-2-thalia-en")

    stt = DeepgramSTTService(api_key=deepgram_key)
    llm = OpenAILLMService(
        api_key=groq_key,
        base_url=GROQ_BASE_URL,
        settings=OpenAILLMService.Settings(
            model=GROQ_MODEL,
            system_instruction=build_system_prompt(business),
        ),
    )
    tts = DeepgramTTSService(
        api_key=deepgram_key,
        settings=DeepgramTTSService.Settings(voice=voice),
    )

    tools = ToolsSchema(standard_tools=[_record_lead_schema(), _end_call_schema()])
    context = LLMContext(messages=[], tools=tools)
    user_agg, assistant_agg = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline([
        transport.input(),
        stt,
        user_agg,
        llm,
        tts,
        transport.output(),
        assistant_agg,
    ])
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            enable_metrics=True,
        ),
    )

    async def on_record_lead(params: FunctionCallParams):
        args = params.arguments or {}
        number = normalize_phone(args.get("callback_number", ""))
        lead.name = args.get("name", "") or lead.name
        lead.callback_number = number or args.get("callback_number", "")
        lead.number_confirmed = bool(args.get("number_confirmed", False))
        for field in ("company", "need_type", "equipment", "issue",
                      "urgency", "service_location", "notes"):
            if args.get(field):
                setattr(lead, field, args[field])
        logger.info(f"Lead updated: {lead.name} / {lead.callback_number} / {lead.need_type}")
        await params.result_callback({"status": "saved"})

    async def on_end_call(params: FunctionCallParams):
        await params.result_callback({"status": "ending_call"})
        await task.queue_frames([EndFrame()])

    llm.register_function("record_lead", on_record_lead)
    llm.register_function("end_call", on_end_call)

    runner = PipelineRunner(handle_sigint=False)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Caller connected - starting greeting")
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Caller disconnected")
        await task.cancel()

    await runner.run(task)
    return lead
