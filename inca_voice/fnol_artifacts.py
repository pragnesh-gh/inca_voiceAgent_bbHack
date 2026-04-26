from __future__ import annotations

from datetime import datetime
from typing import Any

from .callback_ics import build_callback_ics
from .fnol_schema import CallbackRequest, FNOLDocument, FNOLField, PolicyMatch, QualityReport, TimelineEvent
from .pdf_render import render_fnol_pdf
from .redaction import redact_markdown


SECTION_MAP = {
    "Safety": "safety",
    "Caller": "caller",
    "Loss": "loss",
    "People": "people",
    "Vehicles": "vehicles",
    "Police": "police",
    "Witnesses": "witnesses",
    "Coverage": "coverage",
    "Evidence": "evidence",
    "Resolution": "resolution",
}


def fnol_document_from_state(state: dict[str, Any], turns: list[dict[str, Any]]) -> FNOLDocument:
    quality = state.get("metadata", {}).get("quality") or {}
    policy_lookup = state.get("metadata", {}).get("policy_lookup") or {}
    policy_fields = state.get("Policy", {}).get("fields", {})
    doc_kwargs: dict[str, Any] = {
        "document_status": state.get("metadata", {}).get("claim_status", "Draft FNOL"),
        "policy_match": PolicyMatch(
            status=policy_lookup.get("status", "not_checked"),
            confidence=float(policy_lookup.get("match_confidence") or 0.0),
            match_reasons=policy_lookup.get("match_reasons") or [],
            policy_number=_field_from_state(policy_fields.get("policy_number")),
            insured_name=_field_from_state(policy_fields.get("insured_name")),
        ),
        "executive_summary": _executive_summary_from_state(state),
        "quality": QualityReport(
            completion_score=float(quality.get("completion_score") or 0.0),
            missing_essentials=[_missing_label(item) for item in quality.get("missing_essentials", [])],
            open_questions=_open_questions(state),
        ),
        "timeline": build_timeline(state, turns),
        "callback": _callback_from_state(state),
    }
    for source, target in SECTION_MAP.items():
        doc_kwargs[target] = {
            name: _field_from_state(value)
            for name, value in (state.get(source, {}).get("fields", {}) or {}).items()
        }
    return FNOLDocument(**doc_kwargs)


def render_fnol_document(doc: FNOLDocument) -> str:
    lines = [
        "# FNOL Auto Loss Notice",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Document status | {_fmt(doc.document_status)} |",
        f"| Policy match | {_policy_match(doc.policy_match)} |",
        f"| Policy number | {_fmt(doc.policy_match.policy_number.value)} |",
        f"| Insured / reporter | {_fmt(_field_value(doc.caller, 'full_name') or doc.policy_match.insured_name.value)} |",
        f"| Date of birth | {_fmt(_field_value(doc.caller, 'date_of_birth'))} |",
        f"| Callback phone | {_fmt(_field_value(doc.caller, 'callback_phone'))} |",
        f"| Date of loss | {_fmt(_field_value(doc.loss, 'date'))} |",
        f"| Time of loss | {_fmt(_field_value(doc.loss, 'time'))} |",
        f"| Loss location | {_fmt(_field_value(doc.loss, 'location'))} |",
        f"| Loss type | {_fmt(_field_value(doc.loss, 'loss_type'))} |",
        f"| Safety status | {_safety_status(doc)} |",
        f"| Documentation completeness | {doc.quality.completion_score:.0%} |",
        "",
        "## Executive Summary",
        doc.executive_summary or "Not established.",
        "",
        "## FNOL Validation Checklist",
    ]
    if doc.quality.missing_essentials:
        for item in doc.quality.missing_essentials:
            lines.append(f"- Missing: {item}")
    else:
        lines.append("- All essential FNOL fields are documented or addressed.")
    for heading, fields in (
        ("Safety", doc.safety),
        ("Caller", doc.caller),
        ("Loss", doc.loss),
        ("People", doc.people),
        ("Vehicles", doc.vehicles),
        ("Police", doc.police),
        ("Witnesses", doc.witnesses),
        ("Coverage", doc.coverage),
        ("Evidence", doc.evidence),
        ("Resolution", doc.resolution),
    ):
        lines.extend(["", f"## {heading}"])
        rows = _captured_rows(fields)
        if rows:
            lines.extend(["", "| Field | Value | Confidence |", "|---|---|---|"])
            lines.extend(rows)
        else:
            lines.append("Not established.")
    if doc.timeline:
        lines.extend(["", "## Key Moment Timeline", "", "| Time | Event | Sentiment | Summary |", "|---|---|---|---|"])
        for event in doc.timeline:
            lines.append(
                f"| {_time_label(event.time_in_call_secs)} | {_fmt(event.event_type)} | {_fmt(event.sentiment)} | {_fmt(event.summary)} |"
            )
    if doc.callback.needed:
        lines.extend(["", "## Callback", _fmt(doc.callback.notes or doc.callback.requested_time)])
    return "\n".join(lines)


def write_shareable_artifacts(trace: Any, raw_markdown: str, doc: FNOLDocument | None = None) -> None:
    redacted = redact_markdown(raw_markdown)
    trace.save_redacted_claim_note(redacted)
    render_fnol_pdf(redacted, trace.redacted_pdf_path)
    render_fnol_pdf(redacted, trace.latest_redacted_pdf_path)
    if doc:
        ics = build_callback_ics(doc.callback)
        if ics:
            trace.save_callback_ics(ics)


def build_timeline(state: dict[str, Any], turns: list[dict[str, Any]]) -> list[TimelineEvent]:
    events = []
    for turn in turns:
        if turn.get("speaker") != "user":
            continue
        text = str(turn.get("text") or "")
        lowered = text.casefold()
        event_type = None
        if any(word in lowered for word in ("hurt", "injured", "verletzt", "hospital", "krankenhaus")):
            event_type = "injury"
        elif any(word in lowered for word in ("safe", "sicher", "home", "zuhause")):
            event_type = "safety"
        elif any(word in lowered for word in ("police", "polizei", "case number", "aktenzeichen")):
            event_type = "police"
        elif any(word in lowered for word in ("callback", "call me", "ruf", "later", "morgen")):
            event_type = "callback"
        elif any(word in lowered for word in ("accident", "crash", "hit", "unfall")):
            event_type = "loss"
        if event_type:
            events.append(
                TimelineEvent(
                    time_in_call_secs=turn.get("time_in_call_secs"),
                    turn_id=turn.get("id"),
                    event_type=event_type,
                    summary=text[:180],
                    sentiment=_sentiment(text),
                )
            )
    if state.get("metadata", {}).get("policy_lookup", {}).get("status") == "verified":
        events.append(
            TimelineEvent(
                time_in_call_secs=None,
                turn_id=None,
                event_type="policy_verification",
                summary="Policyholder matched against demo policy database.",
                sentiment="neutral",
            )
        )
    return events


def _field_from_state(value: dict[str, Any] | None) -> FNOLField:
    value = value or {}
    return FNOLField(
        value=value.get("value"),
        confidence=float(value.get("confidence") or 0.0),
        source_turn_ids=list(value.get("source_turn_ids") or []),
        needs_followup=bool(value.get("needs_followup", True)),
    )


def _executive_summary_from_state(state: dict[str, Any]) -> str:
    loss = state.get("Loss", {}).get("summary", {}).get("value")
    caller = state.get("Caller", {}).get("fields", {}).get("full_name", {}).get("value")
    policy = state.get("Policy", {}).get("fields", {}).get("policy_number", {}).get("value")
    location = state.get("Loss", {}).get("fields", {}).get("location", {}).get("value")
    parts = []
    if loss:
        parts.append(f"Reported loss: {loss}.")
    parts.append(f"Reporter/insured: {_fmt(caller)}.")
    parts.append(f"Policy: {_fmt(policy)}.")
    parts.append(f"Loss location: {_fmt(location)}.")
    return " ".join(parts)


def _callback_from_state(state: dict[str, Any]) -> CallbackRequest:
    next_steps = state.get("Resolution", {}).get("fields", {}).get("callback_expectation", {}).get("value")
    return CallbackRequest(needed=bool(next_steps), requested_time=_parse_datetime(next_steps), notes=str(next_steps) if next_steps else None)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _missing_label(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("label") or item.get("field") or item)
    return str(item)


def _open_questions(state: dict[str, Any]) -> list[str]:
    questions = []
    for section in SECTION_MAP:
        questions.extend(state.get(section, {}).get("open_questions", []) or [])
    return list(dict.fromkeys(str(item) for item in questions))


def _field_value(fields: dict[str, FNOLField], name: str) -> Any:
    field = fields.get(name)
    return field.value if field else None


def _captured_rows(fields: dict[str, FNOLField]) -> list[str]:
    rows = []
    for name, field in fields.items():
        if field.value in (None, "", []):
            continue
        rows.append(f"| {name.replace('_', ' ').title()} | {_fmt(field.value)} | {field.confidence:.0%} |")
    return rows


def _fmt(value: Any) -> str:
    if value in (None, "", []):
        return "Not established"
    return str(value).replace("\n", " ").strip()


def _policy_match(match: PolicyMatch) -> str:
    if match.status == "verified":
        return f"Verified ({match.confidence:.0%})"
    if match.status == "unverified":
        return "Unverified"
    return "Not checked"


def _safety_status(doc: FNOLDocument) -> str:
    safe = _field_value(doc.safety, "safe_location")
    injuries = _field_value(doc.safety, "injuries_reported")
    safe_text = "safe" if safe is True else "unsafe" if safe is False else "safety not established"
    injury_text = "injuries reported" if injuries is True else "no injuries reported" if injuries is False else "injury status not established"
    return f"{safe_text}; {injury_text}"


def _time_label(seconds: float | None) -> str:
    if seconds is None:
        return "post-call"
    minutes = int(seconds // 60)
    remaining = int(seconds % 60)
    return f"{minutes:02d}:{remaining:02d}"


def _sentiment(text: str) -> str:
    lowered = text.casefold()
    if any(word in lowered for word in ("angry", "mad", "wütend", "unacceptable")):
        return "angry"
    if any(word in lowered for word in ("urgent", "now", "immediately", "hospital", "ambulance", "112")):
        return "urgent"
    if any(word in lowered for word in ("scared", "shaken", "worried", "pregnant", "hurt", "verletzt")):
        return "stressed"
    if any(word in lowered for word in ("maybe", "i think", "not sure", "um", "uh")):
        return "uncertain"
    if any(word in lowered for word in ("okay", "fine", "safe", "home")):
        return "calm"
    return "neutral"
