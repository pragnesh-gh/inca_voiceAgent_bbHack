from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any


def lookup_policyholder(
    db_path: str,
    *,
    name: str | None = None,
    date_of_birth: str | None = None,
    phone: str | None = None,
    policy_number: str | None = None,
    license_plate: str | None = None,
) -> dict[str, Any]:
    records = load_policyholders(db_path)
    best: tuple[int, dict[str, str], list[str]] | None = None
    for record in records:
        score, reasons = _score_record(
            record,
            name=name,
            date_of_birth=date_of_birth,
            phone=phone,
            policy_number=policy_number,
            license_plate=license_plate,
        )
        if score > 0 and (best is None or score > best[0]):
            best = (score, record, reasons)
    if not best or best[0] < 2:
        return {"ok": True, "matched": False, "match_confidence": 0.0, "policyholder": None}
    score, record, reasons = best
    return {
        "ok": True,
        "matched": True,
        "match_confidence": min(score / 7, 1.0),
        "match_reasons": reasons,
        "policyholder": public_policyholder(record),
    }


def load_policyholders(db_path: str) -> list[dict[str, str]]:
    path = Path(db_path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def find_policyholder_in_text(db_path: str, text: str) -> dict[str, Any]:
    name = _extract_name(text)
    date_of_birth = _extract_birth_date(text)
    phone = _extract_phone(text)
    policy_number = _extract_policy_number(text)
    license_plate = _extract_plate(text)
    return lookup_policyholder(
        db_path,
        name=name,
        date_of_birth=date_of_birth,
        phone=phone,
        policy_number=policy_number,
        license_plate=license_plate,
    )


def apply_policyholder_match(state: dict[str, Any], lookup_result: dict[str, Any]) -> None:
    if not lookup_result.get("matched"):
        state.setdefault("metadata", {})["policy_lookup"] = {"status": "unverified"}
        return
    record = lookup_result["policyholder"]
    state.setdefault("metadata", {})["policy_lookup"] = {
        "status": "verified",
        "match_confidence": lookup_result.get("match_confidence"),
        "match_reasons": lookup_result.get("match_reasons", []),
    }
    _set_field(state, "Caller", "full_name", record["full_name"], 0.9)
    _set_field(state, "Caller", "date_of_birth", record["date_of_birth"], 0.9)
    _set_field(state, "Caller", "callback_phone", record["phone"], 0.8)
    _set_field(state, "Caller", "email", record["email"], 0.7)
    _set_field(state, "Caller", "preferred_language", record["preferred_language"], 0.7)
    _set_field(state, "Policy", "policy_number", record["policy_number"], 0.95)
    _set_field(state, "Policy", "insured_name", record["full_name"], 0.9)
    _set_field(state, "Policy", "policy_status", record["policy_status"], 0.85)
    _set_field(state, "Policy", "vehicle_on_policy", record["vehicle"], 0.85)
    _set_field(state, "Coverage", "kasko_type", record["coverage"], 0.8)
    _set_field(state, "Coverage", "deductible", _deductible_text(record), 0.75)
    _set_field(state, "Coverage", "werkstattbindung", record["werkstattbindung"], 0.75)
    _set_field(state, "Coverage", "schutzbrief", record["schutzbrief"], 0.75)
    _set_field(state, "Vehicles", "insured_vehicle", record["vehicle"], 0.85)
    _set_field(state, "Vehicles", "insured_plate", record["license_plate"], 0.85)
    _remove_open_question(state, "Caller", "Caller or policyholder identity")
    _remove_open_question(state, "Caller", "Callback phone number")
    _remove_open_question(state, "Policy", "Policy number or alternate lookup detail")
    state["Caller"]["summary"]["value"] = f"{record['full_name']} matched to an active Meridian Mutual auto policy."
    state["Policy"]["summary"]["value"] = (
        f"Verified policy {record['policy_number']} for {record['vehicle']} "
        f"with {record['coverage']} coverage; status {record['policy_status']}."
    )


def public_policyholder(record: dict[str, str]) -> dict[str, str]:
    full_name = f"{record.get('first_name', '').strip()} {record.get('last_name', '').strip()}".strip()
    return {
        "policy_number": record.get("policy_number", ""),
        "full_name": full_name,
        "date_of_birth": record.get("date_of_birth", ""),
        "phone": record.get("phone", ""),
        "email": record.get("email", ""),
        "preferred_language": record.get("preferred_language", ""),
        "address": record.get("address", ""),
        "license_plate": record.get("license_plate", ""),
        "vehicle": record.get("vehicle", ""),
        "first_registration": record.get("first_registration", ""),
        "coverage": record.get("coverage", ""),
        "deductible_vollkasko": record.get("deductible_vollkasko", ""),
        "deductible_teilkasko": record.get("deductible_teilkasko", ""),
        "werkstattbindung": record.get("werkstattbindung", ""),
        "schutzbrief": record.get("schutzbrief", ""),
        "sf_class_liability": record.get("sf_class_liability", ""),
        "sf_class_vollkasko": record.get("sf_class_vollkasko", ""),
        "policy_status": record.get("policy_status", ""),
    }


def _score_record(
    record: dict[str, str],
    *,
    name: str | None,
    date_of_birth: str | None,
    phone: str | None,
    policy_number: str | None,
    license_plate: str | None,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    full_name = normalize(f"{record.get('first_name', '')} {record.get('last_name', '')}")
    if policy_number and normalize(policy_number) == normalize(record.get("policy_number", "")):
        score += 5
        reasons.append("policy_number")
    if phone and _digits(phone) and _digits(phone) == _digits(record.get("phone", "")):
        score += 4
        reasons.append("phone")
    if license_plate and normalize(license_plate) == normalize(record.get("license_plate", "")):
        score += 4
        reasons.append("license_plate")
    if date_of_birth and date_of_birth == record.get("date_of_birth"):
        score += 3
        reasons.append("date_of_birth")
    if name:
        normalized_name = normalize(name)
        raw_parts = f"{record.get('first_name', '')} {record.get('last_name', '')}".split()
        parts = [normalize(part) for part in raw_parts if len(normalize(part)) > 2]
        hits = sum(1 for part in parts if part in normalized_name or part in normalize(name))
        if hits:
            score += min(hits, 2)
            reasons.append("name")
    return score, reasons


def _set_field(state: dict[str, Any], section: str, slot: str, value: Any, confidence: float) -> None:
    field = state[section]["fields"].setdefault(slot, {"value": None, "confidence": 0.0, "source_turn_ids": [], "needs_followup": True})
    if field.get("value") in (None, "", []) or confidence >= float(field.get("confidence") or 0):
        field.update({"value": value, "confidence": confidence, "source_turn_ids": [], "needs_followup": False})


def _remove_open_question(state: dict[str, Any], section: str, question: str) -> None:
    questions = state.get(section, {}).get("open_questions", [])
    if isinstance(questions, list):
        state[section]["open_questions"] = [item for item in questions if item != question]


def _deductible_text(record: dict[str, str]) -> str:
    parts = []
    if record.get("deductible_vollkasko"):
        parts.append(f"Vollkasko EUR {record['deductible_vollkasko']}")
    if record.get("deductible_teilkasko"):
        parts.append(f"Teilkasko EUR {record['deductible_teilkasko']}")
    return "; ".join(parts)


def _extract_name(text: str) -> str | None:
    match = re.search(r"\b(?:my name is|i am|i'm|ich bin)\s+([A-Za-zÄÖÜäöüß .'-]{2,80})", text, re.IGNORECASE)
    if not match:
        return None
    name = re.split(
        r"\b(?:and|und|born|geboren|date of birth|dob|birthday)\b",
        match.group(1),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return name.strip(" .,-")


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
    match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-zÄÖÜäöüß]+),?\s+(\d{4})", text, re.IGNORECASE)
    if match:
        month = months.get(match.group(2).casefold())
        if month:
            return f"{match.group(3)}-{month}-{int(match.group(1)):02d}"
    match = re.search(r"\b([A-Za-zÄÖÜäöüß]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", text, re.IGNORECASE)
    if match:
        month = months.get(match.group(1).casefold())
        if month:
            return f"{match.group(3)}-{month}-{int(match.group(2)):02d}"
    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    return match.group(0) if match else None


def _extract_phone(text: str) -> str | None:
    match = re.search(r"(\+?\d[\d\s().-]{6,}\d)", text)
    return match.group(1) if match else None


def _extract_policy_number(text: str) -> str | None:
    match = re.search(r"\b(MM-KFZ-\d{4}|[A-Z]{2,5}-[A-Z0-9-]{4,})\b", text, re.IGNORECASE)
    return match.group(1) if match else None


def _extract_plate(text: str) -> str | None:
    match = re.search(r"\bB[- ]?[A-Z]{1,2}[- ]?\d{3,4}\b", text, re.IGNORECASE)
    return match.group(0) if match else None


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold().replace("ü", "ue").replace("ö", "oe").replace("ä", "ae").replace("ß", "ss"))


def _digits(value: str) -> str:
    return re.sub(r"\D+", "", value)
