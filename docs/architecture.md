# Architecture

Primary target path: Twilio inbound phone call -> `/twilio/voice` -> ElevenLabs Register Twilio Call -> ElevenLabs-owned phone agent -> ElevenLabs post-call webhook -> local claims scribe.

The direct Twilio Media Streams path remains in the repo as fallback/debug infrastructure, but it is no longer the competition default.

## Runtime Shape

Primary live-call runtime:

```text
caller phone
  -> Twilio Programmable Voice
  -> POST /twilio/voice
  -> ElevenLabs register_call(...)
  <- ElevenLabs TwiML
  -> ElevenLabs handles ASR, turn-taking, interruption handling, TTS, and phone audio
  -> POST /elevenlabs/post-call after the call
  -> ClaimsScribe writes transcript, claim_state.json, and claim_note.md
```

Fallback local runtime:

```text
caller phone
  -> Twilio Programmable Voice
  -> POST /twilio/voice
  <- TwiML with <Connect><Stream url="wss://PUBLIC_HOST/twilio/media">
  -> WSS /twilio/media
  -> inbound mulaw/8000 frames
  -> optional ai-coustics enhancement/resampling
  -> STT partial/final text
  -> Gemini claim intake response policy
  -> Gradium streaming TTS
  -> convert TTS audio to raw mulaw/8000 base64
  <- outbound Twilio media + mark frames
```

Twilio documents bidirectional streams as the mode where the WebSocket app receives audio and sends audio back into the call. It is started with `<Connect><Stream>`, and Twilio only continues later TwiML after the WebSocket closes. Source: [Twilio Media Streams](https://www.twilio.com/docs/voice/media-streams), [TwiML Stream](https://www.twilio.com/docs/voice/twiml/stream).

## Proposed Server Endpoints

`POST /twilio/voice`

- Input: Twilio voice webhook form body.
- Output: XML TwiML.
- Primary behavior: when `USE_ELEVENLABS_REGISTER_CALL=1`, call ElevenLabs Register Twilio Calls and return the TwiML string from ElevenLabs.
- Fallback behavior: return a bidirectional stream. Keep the tunnel URL private for the hackathon path; add `X-Twilio-Signature` validation before production exposure.

```xml
<Response>
  <Connect>
    <Stream url="wss://PUBLIC_HOST/twilio/media">
      <Parameter name="agent" value="inca-fnol" />
    </Stream>
  </Connect>
</Response>
```

`POST /elevenlabs/post-call`

- Input: ElevenLabs post-call webhook payload.
- Output: JSON status.
- Required behavior: verify signature when `ELEVENLABS_WEBHOOK_SECRET` is set, store timestamped transcript artifacts, and update the structured claim note.

`WebSocket /twilio/media`

- Input from Twilio: `connected`, `start`, `media`, `dtmf`, `mark`, `stop`.
- Output to Twilio: `media`, `mark`, `clear`.
- Store `callSid`, `streamSid`, sequence metadata, transcript, structured claim draft, and timing stats per connection.

`GET /health`

- Returns `200 OK` when env vars are present and provider clients can be constructed.

## Env Vars

Do not commit values.

```text
PUBLIC_BASE_URL=https public host without path
TWILIO_ACCOUNT_SID=
TWILIO_API_KEY=
TWILIO_API_SECRET=
TWILIO_PHONE_NUMBER=
GRADIUM_API_KEY=
GRADIUM_ASR_ENDPOINT=wss://api.gradium.ai/api/speech/asr
GRADIUM_TTS_ENDPOINT=wss://api.gradium.ai/api/speech/tts
GRADIUM_TTS_VOICE_ID=
GRADIUM_STT_MODEL=default
GRADIUM_TTS_MODEL=default
AIC_SDK_LICENSE=
AICOUSTICS_API_KEY=
AICOUSTICS_MODEL_ID=quail-l-8khz
GOOGLE_API_KEY=
GEMINI_PRIMARY_MODEL=gemini-3-flash-preview
GEMINI_FALLBACK_MODEL=gemini-2.5-flash
USE_ELEVENLABS_REGISTER_CALL=1
ELEVENLABS_API_KEY=
ELEVENLABS_AGENT_ID=
ELEVENLABS_WEBHOOK_SECRET=
```

## Audio Contracts

- Twilio inbound and outbound media payloads are raw `audio/x-mulaw` at 8000 Hz, mono, base64 encoded. Source: [Twilio WebSocket messages](https://www.twilio.com/docs/voice/media-streams/websocket-messages).
- Gradium TTS should request `ulaw_8000`; for Twilio playback, send raw mu-law/8000 bytes base64 encoded without file headers. Source: [Gradium API reference](https://docs.gradium.ai/api-reference/introduction).
- ai-coustics SDK examples use float32 NumPy arrays and model-specific optimal frame sizes; this is an internal processing format, not what Twilio sends. Source: [ai-coustics SDK quickstart](https://docs.ai-coustics.com/tutorials/sdk-quickstart).

## Main Failure Modes

- Sending WAV headers to Twilio: Twilio warns that outbound `media.payload` must not contain file header bytes.
- TTS chunk splitting mid-word: Gradium inserts whitespace between text messages, so split only on whitespace and keep punctuation attached.
- Treating `<Start><Stream>` as bidirectional: use `<Connect><Stream>` for the voice agent path.
- Missing `clear` on interruption: caller barge-in should clear buffered outbound audio before responding.
