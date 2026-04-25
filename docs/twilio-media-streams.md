# Twilio Media Streams

Use Twilio Media Streams directly from the phone call to our Python server. For the agent, use bidirectional streaming via `<Connect><Stream>`, because the server must both receive caller audio and send synthesized speech back. Sources: [Media Streams overview](https://www.twilio.com/docs/voice/media-streams), [TwiML Stream](https://www.twilio.com/docs/voice/twiml/stream).

## TwiML

```xml
<Response>
  <Connect>
    <Stream url="wss://PUBLIC_HOST/twilio/media">
      <Parameter name="agent" value="inca-fnol" />
      <Parameter name="env" value="demo" />
    </Stream>
  </Connect>
</Response>
```

Notes:

- `wss` is required for the stream URL.
- Query strings are not supported on the `<Stream url>`; use custom `<Parameter>` values.
- `<Connect><Stream>` blocks later TwiML until the WebSocket closes.
- For bidirectional streams, Twilio allows one stream per call.

## Webhook Endpoint

`POST /twilio/voice`

Response headers:

```text
Content-Type: application/xml
```

Security:

- For the hackathon tunnel path, keep the URL private and rotate it when needed.
- Add `X-Twilio-Signature` validation before production exposure.

## WebSocket Endpoint

`WebSocket /twilio/media`

On open, expect:

```json
{ "event": "connected", "protocol": "Call", "version": "1.0.0" }
```

Then:

```json
{
  "event": "start",
  "sequenceNumber": "1",
  "start": {
    "accountSid": "AC...",
    "streamSid": "MZ...",
    "callSid": "CA...",
    "tracks": ["inbound"],
    "mediaFormat": {
      "encoding": "audio/x-mulaw",
      "sampleRate": 8000,
      "channels": 1
    },
    "customParameters": {
      "agent": "inca-fnol"
    }
  },
  "streamSid": "MZ..."
}
```

Twilio media event:

```json
{
  "event": "media",
  "sequenceNumber": "4",
  "media": {
    "track": "inbound",
    "chunk": "2",
    "timestamp": "5",
    "payload": "base64-mulaw-audio"
  },
  "streamSid": "MZ..."
}
```

Twilio stop event:

```json
{
  "event": "stop",
  "sequenceNumber": "5",
  "stop": {
    "accountSid": "AC...",
    "callSid": "CA..."
  },
  "streamSid": "MZ..."
}
```

DTMF event:

```json
{
  "event": "dtmf",
  "streamSid": "MZ...",
  "sequenceNumber": "6",
  "dtmf": {
    "track": "inbound_track",
    "digit": "1"
  }
}
```

Source for message shapes and fields: [Twilio WebSocket messages](https://www.twilio.com/docs/voice/media-streams/websocket-messages).

## Server-to-Twilio Messages

Send audio:

```json
{
  "event": "media",
  "streamSid": "MZ...",
  "media": {
    "payload": "base64-raw-mulaw-8000"
  }
}
```

Then send a mark:

```json
{
  "event": "mark",
  "streamSid": "MZ...",
  "mark": {
    "name": "assistant-turn-0007"
  }
}
```

Interrupt buffered audio:

```json
{
  "event": "clear",
  "streamSid": "MZ..."
}
```

Twilio requires outbound audio payloads to be base64 encoded raw `audio/x-mulaw` at 8000 Hz and warns against including audio file header bytes. Source: [Twilio WebSocket messages](https://www.twilio.com/docs/voice/media-streams/websocket-messages).
