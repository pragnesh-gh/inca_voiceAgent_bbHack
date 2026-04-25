# Gradium

Gradium is the target STT/TTS provider in this repo. Its API reference lists REST and WebSocket endpoints for text-to-speech, speech-to-text, voices, pronunciations, and metering. It authenticates with `x-api-key`. Source: [Gradium API reference](https://docs.gradium.ai/api-reference/introduction).

## Env Vars

```text
GRADIUM_API_KEY=
GRADIUM_TTS_VOICE_ID=
GRADIUM_TTS_MODEL=default
GRADIUM_STT_MODEL=default
```

## Base URLs

```text
REST:      https://api.gradium.ai/api
WebSocket: wss://api.gradium.ai/api
```

## TTS WebSocket

Connection:

```text
wss://api.gradium.ai/api/speech/tts
x-api-key: ${GRADIUM_API_KEY}
```

First message must be setup:

```json
{
  "type": "setup",
  "model_name": "default",
  "voice_id": "GRADIUM_TTS_VOICE_ID",
  "output_format": "ulaw_8000"
}
```

Expected ready:

```json
{
  "type": "ready",
  "request_id": "uuid"
}
```

Stream text:

```json
{
  "type": "text",
  "text": "Okay, I can help get the claim started."
}
```

Audio response:

```json
{
  "type": "audio",
  "audio": "base64..."
}
```

End:

```json
{ "type": "end_of_stream" }
```

Gradium documents `ulaw_8000` as an available TTS output format. That is the preferred Twilio path because Twilio outbound media expects raw mu-law/8000 audio, base64 encoded in a `media.payload`. Source: [Gradium API reference](https://docs.gradium.ai/api-reference/introduction).

## Text Chunking Rule

Do not split TTS input inside a word or detach punctuation. Gradium inserts whitespace between consecutive text messages, so `"foo"` then `"."` becomes `"foo ."` and sounds wrong. Prefer sentence or phrase chunks with punctuation attached.

## STT

Connection:

```text
wss://api.gradium.ai/api/speech/asr
x-api-key: ${GRADIUM_API_KEY}
```

First message:

```json
{
  "type": "setup",
  "model_name": "default",
  "input_format": "pcm"
}
```

Gradium expects PCM input at 24 kHz, 16-bit signed little-endian, mono, with 1920 samples per 80 ms frame. The server converts Twilio's 8 kHz mu-law frames into 24 kHz PCM before sending `audio` messages. Source: [Gradium STT WebSocket docs](https://docs.gradium.ai/api-reference/endpoint/stt-websocket).
