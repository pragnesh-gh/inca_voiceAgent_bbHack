from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from google import genai
from google.genai import types

from .config import Settings


SECTIONS = ("Safety", "Caller", "Policy", "Loss", "People", "Vehicles", "Police", "Witnesses", "Coverage", "Evidence", "Resolution")


def empty_claim_state() -> dict[str, Any]:
    state: dict[str, Any] = {
        "metadata": {
            "schema": "SAFETY_CALLER_POLICY_LOSS_PEOPLE_VEHICLES_POLICE_WITNESSES_COVERAGE_EVIDENCE_RESOLUTION_V1",
            "language_observed": [],
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
        "Caller": ("full_name", "callback_phone", "email", "relationship_to_policy", "preferred_language"),
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
        self._client = genai.Client(api_key=settings.google_api_key) if settings.google_api_key else None

    async def record_turn(self, speaker: str, text: str) -> None:
        turn = {"id": len(self.turns) + 1, "speaker": speaker, "text": text}
        self.turns.append(turn)
        self._heuristic_update(turn)
        if self._client and speaker == "user":
            await self._llm_update()
        self.trace.save_claim_state(self.state)

    async def close(self) -> None:
        self.trace.save_claim_state(self.state)
        self.trace.save_claim_note(self.render_note())

    def render_note(self) -> str:
        lines = ["# Claim Intake Note", ""]
        for section in SECTIONS:
            data = self.state[section]
            summary = data["summary"]["value"] or "Not established."
            lines.append(f"## {section}")
            lines.append(str(summary))
            if data["facts"]:
                lines.append("")
                lines.extend(f"- {fact}" for fact in data["facts"][:8])
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
        if any(word in lower for word in ("my name", "i am", "ich bin", "policy", "police number", "phone number", "callback")):
            self._add_fact("Caller", text, turn["id"])
        if any(word in lower for word in ("policy", "versicherung", "kasko", "vollkasko", "teilkasko", "haftpflicht", "selbstbeteiligung")):
            self._add_fact("Policy", text, turn["id"])
        if any(word in lower for word in ("crash", "accident", "collision", "hit", "deer", "theft", "stolen", "unfall", "gekracht")):
            self._add_fact("Loss", text, turn["id"])
        if any(word in lower for word in ("family", "passenger", "driver", "police", "witness", "familie", "polizei")):
            self._add_fact("People", text, turn["id"])
        if any(word in lower for word in ("police", "polizei", "case number", "report number", "aktenzeichen")):
            self._add_fact("Police", text, turn["id"])
        if any(word in lower for word in ("witness", "witnesses", "zeuge", "zeugen")):
            self._add_fact("Witnesses", text, turn["id"])
        if any(word in lower for word in ("car", "vehicle", "plate", "license", "vin", "auto", "kennzeichen")):
            self._add_fact("Vehicles", text, turn["id"])
        if re.search(r"\b[A-Z]{1,3}[- ]?[A-Z]{1,3}[- ]?\d{2,4}\b", text):
            self._add_fact("Vehicles", f"Possible plate or policy detail: {text}", turn["id"])

    def _add_fact(self, section: str, text: str, turn_id: int) -> None:
        fact_text = f"Turn {turn_id}: {text}"
        facts = self.state[section]["facts"]
        if fact_text not in facts:
            facts.append(fact_text)
        if not self.state[section]["summary"]["value"]:
            self.state[section]["summary"] = field(text, 0.45, [turn_id])

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


def _merge_state(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(old)
    for key, value in new.items():
        if key in SECTIONS or key == "metadata":
            merged[key] = value
    return merged
