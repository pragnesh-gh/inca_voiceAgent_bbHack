from __future__ import annotations

import re


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
DOB_RE = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")
POLICY_RE = re.compile(r"\b(?:MM-KFZ-\d{4}|[A-Z]{2,5}-[A-Z0-9-]{4,})\b", re.IGNORECASE)
PLATE_RE = re.compile(r"\b[A-ZÄÖÜ]{1,3}[- ][A-ZÄÖÜ]{1,2}[- ]\d{3,4}\b", re.IGNORECASE)
VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)
ADDRESS_RE = re.compile(
    r"\b([A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]+(?:strasse|straße|allee|platz|weg|ring)\s+\d+[A-Za-z]?,\s+\d{5}\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß -]+))",
    re.IGNORECASE,
)


def redact_markdown(text: str) -> str:
    redacted = ADDRESS_RE.sub(lambda match: f"[ADDRESS], {match.group(2).strip()}", text)
    redacted = EMAIL_RE.sub("[EMAIL]", redacted)
    redacted = DOB_RE.sub("[DOB]", redacted)
    redacted = VIN_RE.sub("[VIN]", redacted)
    redacted = PLATE_RE.sub("[PLATE]", redacted)
    redacted = POLICY_RE.sub("[POLICY]", redacted)
    redacted = PHONE_RE.sub("[PHONE]", redacted)
    return redacted
