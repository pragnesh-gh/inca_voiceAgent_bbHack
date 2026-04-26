from __future__ import annotations

from datetime import timedelta, timezone

from .fnol_schema import CallbackRequest


def build_callback_ics(callback: CallbackRequest) -> str | None:
    if not callback.needed or not callback.requested_time:
        return None
    start = callback.requested_time.astimezone(timezone.utc)
    end = start + timedelta(minutes=15)
    description = _ics_escape(callback.notes or "Follow up on FNOL auto loss notice.")
    return "\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Meridian Mutual//Inca FNOL//EN",
            "BEGIN:VEVENT",
            f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
            "SUMMARY:Meridian Mutual FNOL callback",
            f"DESCRIPTION:{description}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")
