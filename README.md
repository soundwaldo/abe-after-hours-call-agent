# After-Hours AI Call Agent

An open-source AI voice agent that answers your business line when you can't —
after hours, on busy lines, on no-answer. It takes the caller's information
like a good receptionist and texts you a lead summary the moment the call ends.

Built for **Arizona's Best Equipment** (forklift sales, rentals, parts &
service — Phoenix, AZ), but the business is one YAML file: fork it, edit
`config/business.yaml`, and it's yours.

## How it works

```
Caller dials your number
        │ (forwards on no-answer / after hours)
        ▼
Twilio number ──POST /voice──▶ this server ──TwiML──▶ Twilio
        │                                              │ opens media stream
        │                                              ▼
        │                                     wss://your-host/ws
        │                                              │
        │            ┌─────────────────────────────────┘
        │            ▼
        │   Pipecat pipeline (per call):
        │   Twilio audio → Deepgram STT → Groq LLM → Deepgram TTS → Twilio audio
        │            │
        │   LLM calls record_lead() as info comes in,
        │   end_call() after the closing line
        │            │
        │            ▼ call ends
        │   Lead summary SMS → owner's mobile (via Twilio)
```

The agent greets, collects name → callback number (read back and confirmed) →
company → need (repair / buy / rent / parts) → equipment → issue → urgency →
location, then closes with a callback promise. It never quotes prices, never
promises times beyond "first thing in the morning", and never takes payments.

## Stack (all open-source framework, pay-per-use services)

| Piece | Choice | Cost |
|---|---|---|
| Voice framework | [Pipecat](https://github.com/pipecat-ai/pipecat) (BSD-2-Clause, Python) | free |
| Telephony | Twilio number + Media Streams | ~$1.15/mo + ~$0.014/min (account requires a one-time $20 minimum deposit — prepaid credit that usage draws from) |
| Speech-to-text | Deepgram Nova-3 (streaming) | free tier, then ~$0.004/min |
| Brain | Groq `llama-3.3-70b-versatile` (OpenAI-compatible API) | free tier |
| Text-to-speech | Deepgram Aura-2 | free tier, then per char |
| Hosting | Railway (Dockerfile) | free tier / ~$5/mo |

Realistic cost for a shop: a **one-time $20 Twilio account deposit** (prepaid
credit), then **under $10/month** unless the phone never stops ringing.

## Setup

### 1. API keys

| Key | Where | Env var |
|---|---|---|
| Twilio Account SID + Auth Token | [console.twilio.com](https://console.twilio.com) | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` |
| Deepgram | [console.deepgram.com](https://console.deepgram.com) | `DEEPGRAM_API_KEY` |
| Groq | [console.groq.com](https://console.groq.com/keys) | `GROQ_API_KEY` |

```bash
cp .env.example .env
# fill in the values
```

### 2. Make it your business

Edit `config/business.yaml`: name, address, phone, hours, services, greeting,
intake fields, and rules. The system prompt is generated from it — no code
changes needed.

### 3. Run locally

```bash
pip install -r requirements.txt
uvicorn src.server:app --port 7860
```

For Twilio to reach you locally, expose the port (e.g. `ngrok http 7860`),
set `PUBLIC_HOST=your-ngrok-host`, and point the Twilio number's voice webhook
at `https://your-ngrok-host/voice`.

### 4. Deploy to Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new)

Or manually: new project → deploy from repo → Railway builds the Dockerfile →
set the env vars → copy the public domain into `PUBLIC_HOST`.

Health check: `GET /health`.

### 5. Wire up Twilio

1. Fund your Twilio account (one-time $20 minimum deposit — prepaid credit) and buy a Twilio phone number (about $1.15/mo, drawn from that balance).
2. Set its **Voice webhook** to `POST https://<your-host>/voice`.
3. On your carrier, set **forward-on-no-answer** (and/or after-hours schedule)
   from your real business number to the Twilio number. Your customers keep
   calling the number they know; the agent only picks up when you don't.

### 6. Test

Call the Twilio number. Give it a name and callback number, describe a broken
forklift, hang up. Your mobile should get the lead SMS within seconds.

## Project layout

```
config/business.yaml   all business facts, greeting, intake fields, rules
src/server.py          FastAPI: /voice (TwiML), /ws (media stream), /health,
                       /dashboard (analytics), /api/stats (JSON)
src/bot.py             Pipecat pipeline: STT → Groq LLM → TTS + function tools
src/persona.py         builds the system prompt from business.yaml
src/lead.py            lead model, phone normalization, SMS formatting
src/notify.py          sends the lead SMS via Twilio
src/store.py           SQLite call + lead log (data/calls.db)
src/dashboard.py       analytics dashboard HTML + stats API (basic-auth)
tests/test_lead.py     unit tests (no keys needed): pytest tests/
tests/test_store.py    store tests
```

## Analytics dashboard

Every call is logged to SQLite (`data/calls.db`): caller, timestamp,
duration, outcome (`lead_captured` / `partial` / `hangup_early`), and the
captured lead fields. No extra infrastructure.

Open `/dashboard` on the deployed host for KPIs (total calls, leads,
capture rate, avg duration), calls-per-day, calls-by-hour (after-hours
spike highlighted), leads by need type and urgency, and a recent-leads
table. Range switcher: 7 / 30 / 90 days.

Protect it with basic auth in production:

```
DASHBOARD_USER=admin
DASHBOARD_PASSWORD=<pick something strong>
```

`GET /api/stats?days=30` returns the same data as JSON for anything else
you want to build on top.

## Lead pipeline

The dashboard has a second tab: **Pipeline**. Every captured lead lands in
the `new` column. Move leads through `new → contacted → quoted → won/lost`
with one click, and add notes per lead.

Stale detection runs automatically: leads sitting in `new` for 24+ hours or
in `contacted`/`quoted` for 72+ hours get flagged in a red banner — "3 leads
need follow-up." This is where deals die, and now it's visible.

API: `GET /api/pipeline` (grouped stages + stale list),
`PATCH /api/leads/{id}` with `{"stage": "quoted"}` and/or `{"notes": "..."}`.

## Customizing

- **Another business?** Edit `config/business.yaml`. That's it.
- **Another voice?** Change `agent.voice` to any Deepgram Aura voice id.
- **More tools?** Add a `FunctionSchema` in `src/bot.py` and register it on
  the LLM (e.g. a calendar check, a CRM lookup).
- **Different LLM?** `OpenAILLMService` takes any OpenAI-compatible
  `base_url` — point it at OpenAI, Azure, or a local model.

## License

MIT — do what you want with it.
