from __future__ import annotations

import json
from typing import Any

from elevenlabs import ElevenLabs

from .config import Settings
from .scribe import ClaimsScribe
from .tracing import CallTrace


def elevenlabs_ready(settings: Settings) -> bool:
    return bool(settings.use_elevenlabs_register_call and settings.elevenlabs_api_key and settings.elevenlabs_agent_id)


def register_elevenlabs_call(
    settings: Settings,
    *,
    from_number: str,
    to_number: str,
    call_sid: str,
) -> str:
    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is missing")
    if not settings.elevenlabs_agent_id:
        raise RuntimeError("ELEVENLABS_AGENT_ID is missing")

    client = ElevenLabs(api_key=settings.elevenlabs_api_key)
    return client.conversational_ai.twilio.register_call(
        agent_id=settings.elevenlabs_agent_id,
        from_number=from_number,
        to_number=to_number,
        direction="inbound",
        conversation_initiation_client_data={
            "dynamic_variables": {
                "caller_number": from_number,
                "called_number": to_number,
                "twilio_call_sid": call_sid,
                "agent_name": "Stefanie",
            }
        },
    )


def verify_or_parse_elevenlabs_webhook(raw_body: str, signature: str | None, settings: Settings) -> dict[str, Any]:
    if settings.elevenlabs_webhook_secret:
        if not signature:
            raise ValueError("Missing ElevenLabs-Signature header")
        client = ElevenLabs(api_key=settings.elevenlabs_api_key or "")
        return client.webhooks.construct_event(
            rawBody=raw_body,
            sig_header=signature,
            secret=settings.elevenlabs_webhook_secret,
        )
    return json.loads(raw_body or "{}")


async def build_claim_from_post_call_webhook(payload: dict[str, Any], settings: Settings) -> dict[str, Any]:
    data = payload.get("data") or {}
    conversation_id = str(data.get("conversation_id") or "elevenlabs-conversation")
    trace = CallTrace(conversation_id, trace_root=settings.trace_dir)
    trace.event("elevenlabs_post_call_webhook", event_type=payload.get("type"), status=data.get("status"))

    scribe = ClaimsScribe(settings, trace)
    for item in data.get("transcript") or []:
        speaker = _speaker_from_elevenlabs_role(item.get("role"))
        text = str(item.get("message") or "").strip()
        if not text:
            continue
        trace.transcript(speaker, text, time_in_call_secs=item.get("time_in_call_secs"))
        await scribe.record_turn(speaker, text)

    await scribe.close()
    trace.save_claim_state(scribe.state)
    note = scribe.render_note()
    trace.save_claim_note(note)
    return {
        "conversation_id": conversation_id,
        "trace_dir": str(trace.dir),
        "claim_state": scribe.state,
        "claim_note": note,
    }


def _speaker_from_elevenlabs_role(role: Any) -> str:
    text = str(role or "").casefold()
    if text in {"agent", "assistant"}:
        return "assistant"
    if text == "user":
        return "user"
    return text or "unknown"
