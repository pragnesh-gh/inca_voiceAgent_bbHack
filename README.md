# Inca Voice Agent - The Human Test

Phone-based auto-claims voice agent for the INCA Human Test hackathon track.

Jurors call a real phone number, role-play an accident claimant, and vote blind on whether the agent sounded human. The system also produces structured FNOL documentation after each call.

## Demo

- Call number: `+49 30 75679047`
- Agent persona: Stefanie Kühne, Meridian Mutual auto claims
- Supported caller languages: English and German, including mixed English/German insurance vocabulary
- Main judge-facing artifact after a call: `traces/LATEST_FNOL_AUTO_LOSS_NOTICE_REDACTED.pdf`

## What It Does

- Accepts inbound phone calls through Twilio.
- Registers each call with an ElevenLabs Conversational AI agent.
- Handles turn-taking, interruptions, bilingual speech, and soft-timeout fillers through ElevenLabs.
- Guides the caller through a human-first auto FNOL flow: safety, orientation, narrative, gap-fill, wrap.
- Looks up demo policyholders through a local server tool backed by `data/mock_policyholders.csv`.
- Optionally checks narrow live context such as weather, roadworks, traffic, closures, and local events through Tavily.
- Stores timestamped traces, transcripts, errors, tool audits, claim state, Markdown notices, and branded redacted PDF notices.
- Provides a transcript-based jury simulator and latency board for iteration.

## Partner Technologies

Primary demo path:

- Twilio Programmable Voice
- ElevenLabs Conversational AI / Register Twilio Calls
- Google Gemini via `google-genai`
- Tavily for narrow live incident context

Fallback and experimental path also included:

- Gradium STT/TTS
- ai-coustics enhancement
- Pipecat Twilio serializer bridge

## Architecture

Primary runtime:

```text
Caller phone
  -> Twilio Programmable Voice
  -> POST /twilio/voice
  -> ElevenLabs register_call(...)
  <- ElevenLabs TwiML
  -> ElevenLabs owns ASR, LLM turn-taking, interruption handling, and TTS
  -> POST /elevenlabs/post-call
  -> local FNOL scribe writes trace artifacts and branded PDF
```

Fallback runtime:

```text
Caller phone
  -> Twilio <Connect><Stream>
  -> local WebSocket /twilio/media
  -> optional ai-coustics
  -> Gradium STT/TTS
  -> Gemini response policy
  -> Twilio outbound media
```

The fallback path remains for debugging and sponsor-stack experiments. The competition demo uses the ElevenLabs Register Call path.

## Setup

Use the conda environment used during development:

```powershell
conda activate inca_bb_hack
python -m pip install -r requirements.txt
```

Create a local `.env` file. Do not commit secrets.

Required for the primary demo path:

```text
USE_ELEVENLABS_REGISTER_CALL=1
ELEVENLABS_API_KEY=
ELEVENLABS_AGENT_ID=
TWILIO_ACCOUNT_SID=
TWILIO_API_KEY=
TWILIO_API_SECRET=
TWILIO_PHONE_NUMBER=+493075679047
GOOGLE_API_KEY=
```

Optional:

```text
ELEVENLABS_WEBHOOK_SECRET=
TAVILY_API_KEY=
TAVILY_TOOL_TOKEN=
POLICY_LOOKUP_TOOL_TOKEN=
PUBLIC_BASE_URL=https://your-stable-ngrok-domain.ngrok-free.dev
SCRIBE_FINAL_MODEL=gemini-2.5-pro
SCRIBE_FALLBACK_MODEL=gemini-2.5-flash
```

## Running Locally

Start the local webhook server:

```powershell
python agent.py
```

Expose the server with a stable HTTPS tunnel:

```powershell
ngrok http 8088 --domain <your-ngrok-domain>
```

If the Twilio Voice URL needs to be set, point only this demo number at the active tunnel:

```powershell
python scripts\configure_twilio_media_streams.py --public-url https://<your-ngrok-domain> --apply
```

Important: the shared hackathon Twilio account may contain other teams' numbers. Confirm `TWILIO_PHONE_NUMBER=+493075679047` before running any Twilio configuration script.

Health check:

```powershell
curl http://127.0.0.1:8088/health
```

## Post-call Artifacts

After a call ends, the ElevenLabs post-call webhook writes:

```text
traces/<trace>/transcript.jsonl
traces/<trace>/events.jsonl
traces/<trace>/errors.jsonl
traces/<trace>/tools.jsonl
traces/<trace>/claim_state.json
traces/<trace>/FNOL_AutoLossNotice_<conversation-id>.md
traces/<trace>/FNOL_AutoLossNotice_<conversation-id>_REDACTED.md
traces/<trace>/FNOL_AutoLossNotice_<conversation-id>_REDACTED.pdf
```

Latest shortcuts:

```text
traces/LATEST_FNOL_AUTO_LOSS_NOTICE.md
traces/LATEST_FNOL_AUTO_LOSS_NOTICE_REDACTED.md
traces/LATEST_FNOL_AUTO_LOSS_NOTICE_REDACTED.pdf
traces/LATEST_CLAIM_STATE.json
traces/LATEST_TRACE_DIR.txt
```

For the demo, open:

```text
traces/LATEST_FNOL_AUTO_LOSS_NOTICE_REDACTED.pdf
```

## Evaluation Loop

Run the transcript-based jury simulator and latency board after a call:

```powershell
python scripts\evaluate_latest_call.py
```

Outputs:

```text
traces/LATEST_JURY_SUMMARY.md
traces/LATEST_LATENCY_BOARD.json
traces/eval_runs.csv
```

## Tests

```powershell
python -m unittest discover tests
```

Latest verified locally:

```text
Ran 44 tests ... OK
```

## Documentation

Read in this order:

1. `docs/architecture.md`
2. `docs/elevenlabs.md`
3. `docs/claims-scribe-framework.md`
4. `docs/meridian-fnol-fields.md`
5. `docs/test-checklist.md`
6. `SUBMISSION_MANUAL.md`

## Safety Notes

- Do not commit `.env` values.
- Do not run Twilio config scripts unless `TWILIO_PHONE_NUMBER` is confirmed as `+493075679047`.
- The live call connection path is intentionally protected; see `AGENTS.md`.
- Raw traces may contain PII. Share the redacted Markdown/PDF artifacts for demos.
