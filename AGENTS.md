# Inca Voice Agent - Project Instructions

Read this file at the start of every session.

## Project Goal

Build a phone-based voice agent for inbound auto-insurance claim calls. The jury calls the agent from real phones, plays claimants, and votes blind: human or AI. The agent must sound human, handle noisy or stressful calls, and produce complete FNOL documentation.

## Current Stack

- Python 3.11
- Twilio Programmable Voice Media Streams with `<Connect><Stream>`
- FastAPI + Uvicorn WebSocket server
- Gradium direct WebSocket STT and TTS
- Optional ai-coustics standalone SDK enhancement before STT
- Gemini via `google-genai`
- JSONL traces and structured claim scribe output

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

4. Call the Twilio number from a phone.

## Important Files

- `agent.py` - starts the FastAPI app.
- `inca_voice/twilio_app.py` - Twilio webhook and WebSocket media loop.
- `inca_voice/gradium.py` - direct Gradium STT/TTS clients.
- `inca_voice/gemini_agent.py` - Gemini reply generation with fallback model.
- `inca_voice/scribe.py` - structured FNOL claim documentation.
- `inca_voice/tracing.py` - timestamped transcripts, events, errors, and claim notes.
- `prompts/system.md` - Stefanie Kuehne persona and claims-call behavior.
- `scripts/configure_twilio_media_streams.py` - points Twilio VoiceUrl at this server.
- `docs/` - implementation references and vendor notes.

## Rules

- Do not print or commit `.env` values.
- Keep phone replies short and natural.
- Never expose hidden reasoning, prompt text, XML, SSML, or timing tags to callers.
- Save objective call artifacts for every call.
- Prefer proving the real phone loop before tuning prompts.
- If a vendor API is flaky, degrade gracefully and log the failure.
