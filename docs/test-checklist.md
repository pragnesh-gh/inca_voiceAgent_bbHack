# Manual Test Checklist

Use this after changing the runtime or call routing.

## Local Server

- `.env` has Twilio, Gradium, ai-coustics, Gemini, and Tavily keys.
- `GET /health` returns `200`.
- `POST /twilio/voice` returns XML with `<Connect><Stream url="wss://.../twilio/media">`.
- Tunnel URL is private and Twilio is pointed at the current `/twilio/voice` URL.
- Public tunnel supports secure WebSocket on port 443.

## Twilio Stream

- Inbound call reaches `POST /twilio/voice`.
- WebSocket receives `connected`.
- WebSocket receives `start` with `callSid`, `streamSid`, `audio/x-mulaw`, sample rate `8000`, channels `1`.
- WebSocket receives `media` frames while caller speaks.
- Server handles `stop` cleanly when caller hangs up.
- DTMF press logs a `dtmf` event.
- Outbound `media.payload` is raw mulaw/8000 with no WAV header bytes.
- Each assistant utterance sends a `mark`; matching Twilio `mark` is observed.
- Barge-in sends `clear` before the next response.

## Provider Pipeline

- Gradium TTS WebSocket sends `setup` first and receives `ready`.
- TTS text chunks split on whitespace boundaries only.
- TTS requests `ulaw_8000` and sends raw mulaw/8000 to Twilio.
- ai-coustics can be disabled by env flag if latency is too high.
- Gemini uses `GEMINI_PRIMARY_MODEL` with `GEMINI_FALLBACK_MODEL`, returns a short assistant response, and updates claim state.

## Claim Intake

- Agent asks one question at a time.
- Agent captures: caller, policy, date/time/location, what happened, injuries, police, other driver, witnesses, drivability.
- Agent refuses to confirm coverage or liability.
- Final summary includes callback number and next step.
- Transcript and structured claim draft are saved for demo review.

## Adversarial Human-Likeness

- Run the existing detector on the saved transcript.
- Check for robotic tells: long lists, "I understand", repeated full-name confirmations, excessive summaries, no interruptions.
- Make one prompt/docs/runtime adjustment at a time and re-call.
