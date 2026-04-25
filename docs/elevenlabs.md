# ElevenLabs Register-Call Runtime

ElevenLabs is now the primary competition call runtime. Twilio still owns the phone number, but our `/twilio/voice` webhook registers each inbound Twilio call with ElevenLabs and returns the TwiML supplied by ElevenLabs.

Sources:

- ElevenLabs Agents overview: https://elevenlabs.io/docs/eleven-agents/overview
- Twilio native integration: https://elevenlabs.io/docs/eleven-agents/phone-numbers/twilio-integration/native-integration
- Register Twilio calls API: https://elevenlabs.io/docs/eleven-agents/phone-numbers/twilio-integration/register-call
- Conversation flow controls: https://elevenlabs.io/docs/eleven-agents/customization/conversation-flow
- Post-call webhooks: https://elevenlabs.io/docs/eleven-agents/workflows/post-call-webhooks
- Knowledge base: https://elevenlabs.io/docs/eleven-agents/customization/knowledge-base

## Local Runtime

```text
caller phone
  -> Twilio number +493075679047
  -> POST /twilio/voice
  -> ElevenLabs register_call(agent_id, from_number, to_number, direction="inbound")
  <- ElevenLabs TwiML
  -> ElevenLabs handles ASR, turn-taking, interruptions, LLM, TTS, and phone audio
  -> POST /elevenlabs/post-call
  -> ClaimsScribe writes trace artifacts and claim note
```

Required env vars:

```text
USE_ELEVENLABS_REGISTER_CALL=1
ELEVENLABS_API_KEY=
ELEVENLABS_AGENT_ID=
TWILIO_PHONE_NUMBER=+493075679047
```

Optional:

```text
ELEVENLABS_WEBHOOK_SECRET=
```

## Agent Configuration

Configure the ElevenLabs agent in the dashboard with:

- For Register Twilio Calls, set both voice output and ASR input to `mu-law 8000 Hz`. ElevenLabs documents this as required for Twilio. Do not use the generic `PCM 16000 Hz` recommendation for this path.
- Persona: Stefanie Kuehne, introduces herself as "Stefanie".
- Bilingual English/German handling, but default back to English when the caller mixes language.
- CARE-FNOL behavior from `prompts/system.md`.
- Short phone-native replies.
- Interruptions enabled.
- Natural filler/soft-timeout phrases enabled.
- Knowledge base containing policy/FNOL/German insurance notes.

## Fallback

If `register_call` fails or `USE_ELEVENLABS_REGISTER_CALL=0`, `/twilio/voice` falls back to the local Twilio Media Streams loop. That path is useful for debugging and sponsor-stack experiments, but it is no longer the demo-default runtime.
