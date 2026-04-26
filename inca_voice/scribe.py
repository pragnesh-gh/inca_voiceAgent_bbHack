from __future__ import annotations

import asyncio
import json
import re
from contextlib import suppress
from copy import deepcopy
from typing import Any

from google import genai
from google.genai import types

from .config import Settings
from .fnol_artifacts import fnol_document_from_state, render_fnol_document
from .fnol_schema import FNOLDocument


SECTIONS = ("Safety", "Caller", "Policy", "Loss", "People", "Vehicles", "Police", "Witnesses", "Coverage", "Evidence", "Resolution")
FINAL_LLM_UPDATE_TIMEOUT_SECS = 45.0

ESSENTIAL_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("Safety", "safe_location", "Whether caller/vehicle is somewhere safe"),
    ("Safety", "injuries_reported", "Whether anyone is injured"),
    ("Caller", "full_name", "Caller or policyholder identity"),
    ("Caller", "callback_phone", "Callback phone number"),
    ("Policy", "policy_number", "Policy number or alternate lookup detail"),
    ("Loss", "date", "Date of loss"),
    ("Loss", "time", "Time of loss"),
    ("Loss", "location", "Loss location"),
    ("Loss", "loss_type", "Type of loss"),
    ("Loss", "summary", "Narrative summary of what happened"),
    ("Loss", "drivable", "Whether the vehicle is drivable"),
    ("Vehicles", "damage_description", "Vehicle damage description"),
    ("Vehicles", "current_vehicle_location", "Current vehicle location"),
    ("People", "other_party_involved", "Whether another party was involved"),
    ("Police", "called", "Whether police were involved"),
)


def empty_claim_state() -> dict[str, Any]:
    state: dict[str, Any] = {
        "metadata": {
            "schema": "SAFETY_CALLER_POLICY_LOSS_PEOPLE_VEHICLES_POLICE_WITNESSES_COVERAGE_EVIDENCE_RESOLUTION_V1",
            "document_type": "FNOL Auto Loss Notice",
            "claim_status": "Draft FNOL",
            "language_observed": [],
            "quality": {},
        }
    }
    for section in SECTIONS:
        state[section] = {
            "summary": field(),
            "facts": [],
            "open_questions": [],
            "fields": _section_fields(section),
        }
    return state


def _section_fields(section: str) -> dict[str, Any]:
    slots: dict[str, tuple[str, ...]] = {
        "Safety": ("safe_location", "injuries_reported", "emergency_services", "roadside_danger"),
        "Caller": ("full_name", "date_of_birth", "callback_phone", "email", "relationship_to_policy", "preferred_language"),
        "Policy": ("policy_number", "insured_name", "policy_status", "vehicle_on_policy"),
        "Loss": ("loss_type", "date", "time", "location", "summary", "weather", "road_conditions", "drivable", "tow_needed"),
        "People": ("driver", "passengers", "injury_details", "other_party_involved", "other_driver_details"),
        "Vehicles": ("insured_vehicle", "insured_plate", "other_vehicle", "other_plate", "damage_description", "current_vehicle_location"),
        "Police": ("called", "department", "case_number", "officer_name"),
        "Witnesses": ("present", "details"),
        "Coverage": ("kasko_type", "deductible", "werkstattbindung", "schutzbrief", "coverage_questions"),
        "Evidence": ("photos_available", "documents_available", "telematics_or_context", "uncertainties"),
        "Resolution": ("claim_number", "next_steps", "callback_expectation", "repair_or_tow_guidance"),
    }
    return {slot: field() for slot in slots[section]}


def field(value: Any = None, confidence: float = 0.0, source_turn_ids: list[int] | None = None) -> dict[str, Any]:
    return {
        "value": value,
        "confidence": confidence,
        "source_turn_ids": source_turn_ids or [],
        "needs_followup": value in (None, "", []),
    }


class ClaimsScribe:
    def __init__(self, settings: Settings, trace: Any) -> None:
        self.settings = settings
        self.trace = trace
        self.state = empty_claim_state()
        self.turns: list[dict[str, Any]] = []
        self.final_document: FNOLDocument | None = None
        self._client = genai.Client(api_key=settings.google_api_key) if settings.google_api_key else None
        self._llm_task: asyncio.Task[None] | None = None

    async def record_turn(self, speaker: str, text: str, **metadata: Any) -> None:
        turn = {"id": len(self.turns) + 1, "speaker": speaker, "text": text, **metadata}
        self.turns.append(turn)
        if speaker == "user":
            self._heuristic_update(turn)
        if self._client and speaker == "user":
            self._schedule_llm_update()
        self.trace.save_claim_state(self.state)

    async def close(self, *, run_llm: bool = True) -> None:
        if self._llm_task and not self._llm_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._llm_task), timeout=3.0)
            except asyncio.TimeoutError:
                self._llm_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._llm_task
        if run_llm and self._client:
            try:
                await asyncio.wait_for(self._llm_update(), timeout=FINAL_LLM_UPDATE_TIMEOUT_SECS)
            except asyncio.TimeoutError:
                self.trace.error(
                    "scribe_update",
                    f"timed out after {FINAL_LLM_UPDATE_TIMEOUT_SECS:.0f}s while generating final documentation",
                )
        self._finalize_quality()
        self.trace.save_claim_state(self.state)
        self.trace.save_claim_note(self.render_note())

    def _schedule_llm_update(self) -> None:
        if self._llm_task and not self._llm_task.done():
            return
        self._llm_task = asyncio.create_task(self._llm_update())

    def render_note(self) -> str:
        if self.final_document:
            return render_fnol_document(self.final_document)
        quality = self._finalize_quality()
        meta = self.state.get("metadata", {})
        lines = ["# FNOL Auto Loss Notice", ""]
        lines.extend(
            [
                "| Field | Value |",
                "|---|---|",
                f"| Document status | {_fmt(meta.get('claim_status', 'Draft FNOL'))} |",
                f"| Policy match | {_policy_match_label(meta)} |",
                f"| Policy number | {_field_text(self.state, 'Policy', 'policy_number')} |",
                f"| Insured / reporter | {_field_text(self.state, 'Caller', 'full_name')} |",
                f"| Date of birth | {_field_text(self.state, 'Caller', 'date_of_birth')} |",
                f"| Callback phone | {_field_text(self.state, 'Caller', 'callback_phone')} |",
                f"| Date of loss | {_field_text(self.state, 'Loss', 'date')} |",
                f"| Time of loss | {_field_text(self.state, 'Loss', 'time')} |",
                f"| Loss location | {_field_text(self.state, 'Loss', 'location')} |",
                f"| Loss type | {_field_text(self.state, 'Loss', 'loss_type')} |",
                f"| Safety status | {_safety_summary(self.state)} |",
                f"| Documentation completeness | {quality['completion_score']:.0%} |",
                "",
                "## Executive Summary",
                _executive_summary(self.state),
                "",
                "## FNOL Validation Checklist",
            ]
        )
        if quality["missing_essentials"]:
            missing_labels = {item["label"] for item in quality["missing_essentials"]}
            for _, _, label in ESSENTIAL_FIELDS:
                status = "Missing" if label in missing_labels else "Captured"
                lines.append(f"- {status}: {label}")
        else:
            lines.append("- All essential FNOL fields are documented or addressed.")
        lines.append("")
        for section in SECTIONS:
            data = self.state[section]
            summary = data["summary"]["value"] or "Not established."
            lines.append(f"## {section}")
            lines.append(str(summary))
            captured = _captured_fields(data["fields"])
            if captured:
                lines.append("")
                lines.append("| Field | Value | Confidence |")
                lines.append("|---|---|---|")
                lines.extend(captured)
            if data["facts"]:
                lines.append("")
                lines.append("Source notes:")
                lines.extend(f"- {fact}" for fact in data["facts"][:6])
            if data["open_questions"]:
                lines.append("")
                lines.append("Open questions:")
                lines.extend(f"- {item}" for item in data["open_questions"][:8])
            lines.append("")
        return "\n".join(lines)

    def _heuristic_update(self, turn: dict[str, Any]) -> None:
        text = turn["text"]
        lower = text.lower()
        if any(word in lower for word in ("hurt", "injured", "ambulance", "hospital", "112", "safe", "verletzt", "krankenhaus")):
            self._add_fact("Safety", text, turn["id"])
            self._infer_safety_fields(lower, text, turn["id"])
        if any(word in lower for word in ("my name", "i am", "ich bin", "policy", "police number", "phone number", "callback")):
            self._add_fact("Caller", text, turn["id"])
            self._infer_caller_fields(text, lower, turn["id"])
        if any(word in lower for word in ("policy", "versicherung", "kasko", "vollkasko", "teilkasko", "haftpflicht", "selbstbeteiligung")):
            self._add_fact("Policy", text, turn["id"])
            self._infer_policy_fields(text, turn["id"])
        if any(word in lower for word in ("crash", "accident", "collision", "hit", "deer", "theft", "stolen", "unfall", "gekracht")):
            self._add_fact("Loss", text, turn["id"])
            self._set_field("Loss", "summary", text, 0.45, turn["id"])
            self._infer_loss_fields(text, lower, turn["id"])
        if any(word in lower for word in ("family", "passenger", "driver", "police", "witness", "familie", "polizei")):
            self._add_fact("People", text, turn["id"])
            self._infer_people_fields(lower, text, turn["id"])
        if any(word in lower for word in ("police", "polizei", "case number", "report number", "aktenzeichen")):
            self._add_fact("Police", text, turn["id"])
            if any(phrase in lower for phrase in ("no police", "police not", "didn't call police", "keine polizei", "polizei nicht")):
                self._set_field("Police", "called", False, 0.55, turn["id"])
            else:
                self._set_field("Police", "called", True, 0.5, turn["id"])
        if any(word in lower for word in ("witness", "witnesses", "zeuge", "zeugen")):
            self._add_fact("Witnesses", text, turn["id"])
        if any(word in lower for word in ("car", "vehicle", "plate", "license", "vin", "auto", "kennzeichen")):
            self._add_fact("Vehicles", text, turn["id"])
            self._infer_vehicle_fields(text, lower, turn["id"])
        if re.search(r"\b[A-Z]{1,3}[- ]?[A-Z]{1,3}[- ]?\d{2,4}\b", text):
            self._add_fact("Vehicles", f"Possible plate or policy detail: {text}", turn["id"])
            self._set_field("Vehicles", "insured_plate", text, 0.4, turn["id"])

    def _add_fact(self, section: str, text: str, turn_id: int) -> None:
        fact_text = f"Turn {turn_id}: {text}"
        facts = self.state[section]["facts"]
        if fact_text not in facts:
            facts.append(fact_text)
        if not self.state[section]["summary"]["value"]:
            self.state[section]["summary"] = field(text, 0.45, [turn_id])

    def _set_field(self, section: str, slot: str, value: Any, confidence: float, turn_id: int) -> None:
        if value in (None, "", []):
            return
        current = self.state[section]["fields"][slot]
        if current["value"] in (None, "", []):
            self.state[section]["fields"][slot] = field(value, confidence, [turn_id])

    def _infer_safety_fields(self, lower: str, text: str, turn_id: int) -> None:
        if any(phrase in lower for phrase in ("not safe", "unsafe", "danger", "on the highway", "auf der autobahn")):
            self._set_field("Safety", "safe_location", False, 0.55, turn_id)
            self._set_field("Safety", "roadside_danger", True, 0.55, turn_id)
        if any(phrase in lower for phrase in ("i am safe", "we are safe", "somewhere safe", "safe now", "bin sicher", "sind sicher")):
            self._set_field("Safety", "safe_location", True, 0.55, turn_id)
        if any(phrase in lower for phrase in ("no one is hurt", "nobody is hurt", "no injuries", "nicht verletzt", "niemand verletzt")):
            self._set_field("Safety", "injuries_reported", False, 0.6, turn_id)
        elif any(word in lower for word in ("hurt", "injured", "ambulance", "hospital", "verletzt", "krankenhaus")):
            self._set_field("Safety", "injuries_reported", True, 0.55, turn_id)
        if any(word in lower for word in ("112", "ambulance", "police", "polizei", "rettung")):
            self._set_field("Safety", "emergency_services", text, 0.45, turn_id)

    def _infer_caller_fields(self, text: str, lower: str, turn_id: int) -> None:
        phone = re.search(r"(\+?\d[\d\s().-]{6,}\d)", text)
        if phone:
            self._set_field("Caller", "callback_phone", phone.group(1), 0.5, turn_id)
        name_match = re.search(r"\b(?:my name is|i am|i'm|ich bin)\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß .'-]{1,60})", text)
        if name_match:
            self._set_field("Caller", "full_name", name_match.group(1).strip(), 0.45, turn_id)
        date_match = _extract_birth_date(text)
        if date_match:
            self._set_field("Caller", "date_of_birth", date_match, 0.55, turn_id)
        if "daughter" in lower or "son" in lower or "father" in lower or "mother" in lower or "lawyer" in lower:
            self._set_field("Caller", "relationship_to_policy", text, 0.45, turn_id)

    def _infer_policy_fields(self, text: str, turn_id: int) -> None:
        policy = re.search(r"\b(?:policy|police|versicherung)\s*(?:number|nummer|nr\.?)?\s*[:#-]?\s*([A-Z0-9-]{4,})", text, re.IGNORECASE)
        if policy:
            self._set_field("Policy", "policy_number", policy.group(1), 0.5, turn_id)

    def _infer_loss_fields(self, text: str, lower: str, turn_id: int) -> None:
        loss_types = {
            "rear_end": ("rear-ended", "hit from behind", "auffahr"),
            "wildlife": ("deer", "wildlife", "wildunfall", "animal"),
            "theft": ("theft", "stolen", "gestohlen"),
            "parking": ("parking", "parked", "parkschaden"),
            "glass": ("glass", "windshield", "glasbruch"),
            "collision": ("crash", "accident", "collision", "hit", "unfall"),
        }
        for label, terms in loss_types.items():
            if any(term in lower for term in terms):
                self._set_field("Loss", "loss_type", label, 0.5, turn_id)
                break
        if any(phrase in lower for phrase in ("not drivable", "can't drive", "cannot drive", "tow", "towed", "nicht fahrbereit", "abschlepp")):
            self._set_field("Loss", "drivable", False, 0.55, turn_id)
            if "tow" in lower or "abschlepp" in lower:
                self._set_field("Loss", "tow_needed", True, 0.5, turn_id)
        if any(phrase in lower for phrase in ("still drives", "drivable", "can drive", "fahrbereit")):
            self._set_field("Loss", "drivable", True, 0.5, turn_id)
        location = re.search(r"\b(?:at|on|near|in|bei|auf|an)\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß0-9 .'-]{2,80})", text)
        if location:
            self._set_field("Loss", "location", location.group(1).strip(), 0.35, turn_id)

    def _infer_people_fields(self, lower: str, text: str, turn_id: int) -> None:
        if "family" in lower or "passenger" in lower or "familie" in lower:
            self._set_field("People", "passengers", text, 0.45, turn_id)
        if any(phrase in lower for phrase in ("other car", "other driver", "third party", "anderes auto", "gegner")):
            self._set_field("People", "other_party_involved", True, 0.5, turn_id)
        if any(phrase in lower for phrase in ("no other", "nobody else", "kein anderer")):
            self._set_field("People", "other_party_involved", False, 0.5, turn_id)
        if any(word in lower for word in ("hurt", "injured", "hospital", "verletzt", "krankenhaus")):
            self._set_field("People", "injury_details", text, 0.45, turn_id)

    def _infer_vehicle_fields(self, text: str, lower: str, turn_id: int) -> None:
        if any(word in lower for word in ("damage", "bumper", "door", "front", "rear", "windshield", "schaden", "stoßstange")):
            self._set_field("Vehicles", "damage_description", text, 0.45, turn_id)
        if any(phrase in lower for phrase in ("car is at", "vehicle is at", "auto steht", "car is still", "vehicle is still")):
            self._set_field("Vehicles", "current_vehicle_location", text, 0.4, turn_id)

    def _finalize_quality(self) -> dict[str, Any]:
        missing = []
        for section, slot, label in ESSENTIAL_FIELDS:
            if section == "Policy" and slot == "policy_number" and self._has_alternate_policy_lookup():
                continue
            if self.state[section]["fields"][slot]["needs_followup"]:
                missing.append({"section": section, "field": slot, "label": label})
        total = len(ESSENTIAL_FIELDS)
        score = (total - len(missing)) / total if total else 1.0
        quality = {
            "completion_score": score,
            "missing_essentials": missing,
            "turn_count": len(self.turns),
        }
        self.state["metadata"]["quality"] = quality
        for item in missing:
            open_questions = self.state[item["section"]]["open_questions"]
            question = item["label"]
            if question not in open_questions:
                open_questions.append(question)
        return quality

    def _has_alternate_policy_lookup(self) -> bool:
        vehicle_fields = self.state["Vehicles"]["fields"]
        caller_fields = self.state["Caller"]["fields"]
        return any(
            not item["needs_followup"]
            for item in (
                vehicle_fields["insured_plate"],
                vehicle_fields["insured_vehicle"],
                caller_fields["full_name"],
            )
        )

    async def _llm_update(self) -> None:
        prompt = (
            "Update this auto insurance FNOL state from the transcript. "
            "Return valid JSON only, preserving this top-level schema: "
            "Safety, Caller, Policy, Loss, People, Vehicles, Police, Witnesses, "
            "Coverage, Evidence, Resolution, metadata. "
            "Each section must keep summary, facts, open_questions, and fields. "
            "Do not invent facts; use open_questions for missing essentials.\n\n"
            f"Existing state:\n{json.dumps(self.state, ensure_ascii=False)}\n\n"
            f"Transcript:\n{json.dumps(self.turns[-12:], ensure_ascii=False)}"
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self.settings.gemini_fallback_model,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            parsed = json.loads(response.text or "{}")
            if isinstance(parsed, dict) and all(section in parsed for section in SECTIONS):
                self.state = _merge_state(self.state, parsed)
        except Exception as exc:
            self.trace.error("scribe_update", exc)

    async def final_structured_update(self) -> None:
        if not self._client:
            return
        draft = fnol_document_from_state(self.state, self.turns)
        prompt = (
            "Produce a strict, factual FNOLDocument JSON object for an auto insurance first notice of loss. "
            "Use only the transcript, current draft, and tool log. Do not invent missing values. "
            "Keep sensitive raw values in the JSON; redaction happens later. "
            "For every field, include confidence, source_turn_ids, and needs_followup.\n\n"
            f"Current draft:\n{draft.model_dump_json()}\n\n"
            f"Transcript:\n{json.dumps(self.turns, ensure_ascii=False)}\n\n"
            f"Tool log:\n{_read_tool_log(self.trace)}"
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self.settings.scribe_final_model,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=FNOLDocument,
                ),
            )
            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, FNOLDocument):
                self.final_document = parsed
            else:
                self.final_document = FNOLDocument.model_validate_json(response.text or "{}")
        except Exception as exc:
            self.trace.error("scribe_final_update", exc)


def _merge_state(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(old)
    for key, value in new.items():
        if key in SECTIONS or key == "metadata":
            merged[key] = value
    return merged


def _field_text(state: dict[str, Any], section: str, slot: str) -> str:
    value = state.get(section, {}).get("fields", {}).get(slot, {}).get("value")
    return _fmt(value)


def _fmt(value: Any) -> str:
    if value in (None, "", []):
        return "Not established"
    return str(value).replace("\n", " ").strip()


def _policy_match_label(metadata: dict[str, Any]) -> str:
    lookup = metadata.get("policy_lookup") or {}
    status = lookup.get("status")
    if status == "verified":
        confidence = lookup.get("match_confidence")
        if isinstance(confidence, (int, float)):
            return f"Verified ({confidence:.0%})"
        return "Verified"
    if status == "unverified":
        return "Unverified"
    return "Not checked"


def _safety_summary(state: dict[str, Any]) -> str:
    safe = state["Safety"]["fields"]["safe_location"]["value"]
    injuries = state["Safety"]["fields"]["injuries_reported"]["value"]
    safe_text = "safe" if safe is True else "unsafe" if safe is False else "safety not established"
    injury_text = "injuries reported" if injuries is True else "no injuries reported" if injuries is False else "injury status not established"
    return f"{safe_text}; {injury_text}"


def _executive_summary(state: dict[str, Any]) -> str:
    loss = state["Loss"]["summary"]["value"] or state["Loss"]["fields"]["summary"]["value"]
    caller = _field_text(state, "Caller", "full_name")
    policy = _field_text(state, "Policy", "policy_number")
    vehicle = _field_text(state, "Vehicles", "insured_vehicle")
    location = _field_text(state, "Loss", "location")
    police = _field_text(state, "Police", "called")
    pieces = [
        f"Reporter/insured: {caller}.",
        f"Policy: {policy}.",
        f"Vehicle: {vehicle}.",
        f"Loss location: {location}.",
        f"Police involved: {police}.",
    ]
    if loss:
        pieces.insert(0, f"Reported loss: {_fmt(loss)}.")
    return " ".join(pieces)


def _captured_fields(fields: dict[str, Any]) -> list[str]:
    rows = []
    for name, data in fields.items():
        value = data.get("value")
        if value in (None, "", []):
            continue
        confidence = data.get("confidence", 0)
        confidence_text = f"{confidence:.0%}" if isinstance(confidence, (int, float)) else ""
        rows.append(f"| {name.replace('_', ' ').title()} | {_fmt(value)} | {confidence_text} |")
    return rows


def _extract_birth_date(text: str) -> str | None:
    months = {
        "january": "01", "jan": "01", "januar": "01",
        "february": "02", "feb": "02", "februar": "02",
        "march": "03", "mar": "03", "maerz": "03", "märz": "03",
        "april": "04", "apr": "04",
        "may": "05", "mai": "05",
        "june": "06", "jun": "06", "juni": "06",
        "july": "07", "jul": "07", "juli": "07",
        "august": "08", "aug": "08",
        "september": "09", "sep": "09",
        "october": "10", "oct": "10", "oktober": "10", "okt": "10",
        "november": "11", "nov": "11",
        "december": "12", "dec": "12", "dezember": "12", "dez": "12",
    }
    patterns = (
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-zÄÖÜäöüß]+),?\s+(\d{4})",
        r"\b([A-Za-zÄÖÜäöüß]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})",
    )
    day_first = re.search(patterns[0], text, re.IGNORECASE)
    if day_first:
        month = months.get(day_first.group(2).casefold())
        if month:
            return f"{day_first.group(3)}-{month}-{int(day_first.group(1)):02d}"
    month_first = re.search(patterns[1], text, re.IGNORECASE)
    if month_first:
        month = months.get(month_first.group(1).casefold())
        if month:
            return f"{month_first.group(3)}-{month}-{int(month_first.group(2)):02d}"
    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    return iso.group(0) if iso else None


def _read_tool_log(trace: Any) -> str:
    path = getattr(trace, "tools_path", None)
    if not path:
        return "[]"
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return "[]"
