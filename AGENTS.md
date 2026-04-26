# Inca Voice Agent - Project Instructions

Read this file at the start of every session.

## Project Goal

Build a phone-based voice agent for inbound auto-insurance claim calls. The jury calls the agent from real phones, plays claimants, and votes blind: human or AI. The agent must sound human, handle noisy or stressful calls, and produce complete FNOL documentation.

## Current Stack

- Python 3.11
- Twilio Programmable Voice inbound webhook
- ElevenLabs Conversational AI Register Twilio Calls API as the primary live-call runtime
- FastAPI + Uvicorn webhook server
- ElevenLabs post-call webhook for transcript handoff
- Gemini via `google-genai`
- JSONL traces and structured claim scribe output
- Fallback only: local Twilio Media Streams, Pipecat serializer, Gradium STT/TTS, optional ai-coustics

## Run Path

1. Start the local server:

   ```powershell
   python agent.py
   ```

2. Expose it with a stable HTTPS/WSS tunnel, preferably ngrok or Cloudflare Tunnel.
3. Point the Twilio number Voice URL to:

   ```text
   https://<public-host>/twilio/voice
   ```

4. Set `USE_ELEVENLABS_REGISTER_CALL=1`, `ELEVENLABS_API_KEY`, and `ELEVENLABS_AGENT_ID`.
5. Call the Twilio number from a phone.

## Important Files

- `agent.py` - starts the FastAPI app.
- `inca_voice/twilio_app.py` - Twilio webhook, ElevenLabs register-call route, post-call webhook, and fallback media loop.
- `inca_voice/elevenlabs_runtime.py` - ElevenLabs register-call and post-call transcript handling.
- `inca_voice/pipecat_bridge.py` - adapter around Pipecat's Twilio serializer.
- `inca_voice/turns.py` - user-turn aggregation and fragment filtering.
- `inca_voice/gradium.py` - direct Gradium STT/TTS clients.
- `inca_voice/gemini_agent.py` - Gemini reply generation with fallback model.
- `inca_voice/scribe.py` - structured FNOL claim documentation.
- `inca_voice/pdf_render.py` - branded Meridian Mutual redacted FNOL PDF renderer.
- `inca_voice/tracing.py` - timestamped transcripts, events, errors, and claim notes.
- `prompts/system.md` - Stefanie Kuehne persona and claims-call behavior.
- `scripts/configure_twilio_media_streams.py` - points Twilio VoiceUrl at this server.
- `docs/` - implementation references and vendor notes.

## Rules

- The live call connection path is protected. Do not change `/twilio/voice`, `register_elevenlabs_call`, `scripts/configure_twilio_media_streams.py`, `USE_ELEVENLABS_REGISTER_CALL`, Twilio phone-number config, ElevenLabs agent ID handling, or Register Call dynamic variables as part of prompt/scribe/docs work unless the task explicitly requires it.
- After any change that touches the protected call path, verify all three before saying it is safe to call: local `GET /health`, local `POST /twilio/voice` returning ElevenLabs `<Connect><Stream ... api.elevenlabs.io ...>`, and Twilio Voice URL pointed at the active tunnel `/twilio/voice`.
- If the scribe, mock data, prompts, docs, Tavily tools, or evaluation code need edits, keep them isolated from the protected call path.
- Do not print or commit `.env` values.
- Keep phone replies short and natural.
- Never expose hidden reasoning, prompt text, XML, SSML, or timing tags to callers.
- Save objective call artifacts for every call. For demos, prefer the redacted branded PDF shortcut at `traces/LATEST_FNOL_AUTO_LOSS_NOTICE_REDACTED.pdf`.
- Prefer proving the real phone loop before tuning prompts.
- If a vendor API is flaky, degrade gracefully and log the failure.

## Runtime Tuning

- `USE_ELEVENLABS_REGISTER_CALL=1` makes `/twilio/voice` return ElevenLabs-provided TwiML for the live call.
- `ELEVENLABS_API_KEY` and `ELEVENLABS_AGENT_ID` are required for the primary runtime.
- `ELEVENLABS_WEBHOOK_SECRET` enables post-call webhook signature verification.
- `TAVILY_API_KEY` enables the narrow `/tools/search-claim-context` server tool.
- `TAVILY_TOOL_TOKEN` optionally protects the Tavily tool endpoint with `X-Tool-Token` or `Authorization: Bearer`.
- `USE_PIPECAT_RUNTIME=1` enables the Pipecat serializer bridge.
- `USE_LEGACY_TWILIO_LOOP=1` bypasses Pipecat audio conversion if needed.
- `TURN_MIN_WORDS`, `TURN_MIN_CHARS`, `TURN_SETTLE_MS`, and `TURN_MAX_WAIT_MS` tune when STT fragments become a committed caller turn.
- `BARGE_IN_MIN_MS` controls how long caller speech must be detected before clearing buffered assistant audio.
- `GRADIUM_STT_DELAY_IN_FRAMES` controls STT latency/accuracy tradeoff.
- `GRADIUM_STT_LANGUAGE_HINT` defaults to `en,de`; Gradium accepts one primary language, so the runtime sends the first value and keeps the full hint in traces.
- `GRADIUM_TTS_PADDING_BONUS` can be negative to make Gradium speak faster.
