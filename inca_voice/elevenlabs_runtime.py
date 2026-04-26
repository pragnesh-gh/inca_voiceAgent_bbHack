from __future__ import annotations

import json
import asyncio
from typing import Any

from elevenlabs import ElevenLabs

from .config import Settings
from .fnol_artifacts import fnol_document_from_state, write_shareable_artifacts
from .policy_lookup import apply_policyholder_match, find_policyholder_in_text
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


async def build_claim_from_post_call_webhook(
    payload: dict[str, Any],
    settings: Settings,
    *,
    final_mode: str = "sync",
) -> dict[str, Any]:
    data = payload.get("data") or {}
    conversation_id = str(data.get("conversation_id") or "elevenlabs-conversation")
    trace = CallTrace(conversation_id, trace_root=settings.trace_dir, label="elevenlabs-postcall")
    trace.event("elevenlabs_post_call_webhook", event_type=payload.get("type"), status=data.get("status"))

    scribe = ClaimsScribe(settings, trace)
    transcript_text: list[str] = []
    for item in data.get("transcript") or []:
        speaker = _speaker_from_elevenlabs_role(item.get("role"))
        text = str(item.get("message") or "").strip()
        if not text:
            continue
        transcript_text.append(text)
        time_in_call_secs = item.get("time_in_call_secs")
        trace.transcript(speaker, text, time_in_call_secs=time_in_call_secs)
        await scribe.record_turn(speaker, text, time_in_call_secs=time_in_call_secs)

    await scribe.close(run_llm=False)
    policy_match = find_policyholder_in_text(settings.policyholder_db_path, "\n".join(transcript_text))
    apply_policyholder_match(scribe.state, policy_match)
    scribe.final_document = None
    trace.tool_call(
        "lookup_policyholder",
        request_summary={"source": "post_call_transcript"},
        response_summary={
            "matched": policy_match.get("matched"),
            "policy_number": (policy_match.get("policyholder") or {}).get("policy_number"),
        },
        ok=bool(policy_match.get("ok", True)),
    )
    trace.event("policyholder_lookup", matched=policy_match.get("matched"), reasons=policy_match.get("match_reasons", []))
    note = _save_scribe_artifacts(trace, scribe)
    quality = scribe.state.get("metadata", {}).get("quality", {})
    trace.event("claim_quality_check", **quality)
    if final_mode == "background":
        asyncio.create_task(_run_final_scribe_pass(trace, scribe, settings))
    elif final_mode == "sync":
        await _run_final_scribe_pass(trace, scribe, settings)
        note = scribe.render_note()
    return {
        "conversation_id": conversation_id,
        "trace_dir": str(trace.dir),
        "claim_state": scribe.state,
        "claim_note": note,
        "quality": quality,
    }


async def _run_final_scribe_pass(trace: CallTrace, scribe: ClaimsScribe, settings: Settings) -> None:
    if not settings.google_api_key:
        return
    try:
        await asyncio.wait_for(scribe.final_structured_update(), timeout=settings.scribe_final_timeout_secs)
        _save_scribe_artifacts(trace, scribe)
        trace.event("claim_final_artifacts_ready", model=settings.scribe_final_model)
    except asyncio.TimeoutError:
        trace.error("scribe_final_update", f"timed out after {settings.scribe_final_timeout_secs:.0f}s")


def _save_scribe_artifacts(trace: CallTrace, scribe: ClaimsScribe) -> str:
    scribe._finalize_quality()
    if not scribe.final_document:
        scribe.final_document = fnol_document_from_state(scribe.state, scribe.turns)
    trace.save_claim_state(scribe.state)
    note = scribe.render_note()
    trace.save_claim_note(note)
    write_shareable_artifacts(trace, note, scribe.final_document)
    return note


def _speaker_from_elevenlabs_role(role: Any) -> str:
    text = str(role or "").casefold()
    if text in {"agent", "assistant"}:
        return "assistant"
    if text == "user":
        return "user"
    return text or "unknown"
