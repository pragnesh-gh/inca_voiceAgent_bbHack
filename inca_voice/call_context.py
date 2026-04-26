from __future__ import annotations

import asyncio
import inspect
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from .config import Settings
from .tavily_tool import search_claim_context
from .tracing import json_safe, now_iso


APPROVED_SHIFT_ANCHORS = (
    "I just came back from a short break.",
    "The system's a bit slow today, sorry.",
    "It's been a busy claims desk this morning.",
    "I'm just getting my next case open here.",
)

WEEKDAYS_DE = (
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
)


SearchFunc = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]


def build_call_dynamic_variables(
    *,
    from_number: str,
    to_number: str,
    call_sid: str,
    now: datetime | None = None,
    anchor_index: int | None = None,
) -> dict[str, str]:
    current = now or datetime.now(ZoneInfo("Europe/Berlin"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("Europe/Berlin"))
    current = current.astimezone(ZoneInfo("Europe/Berlin"))
    return {
        "caller_number": from_number,
        "called_number": to_number,
        "twilio_call_sid": call_sid,
        "agent_name": "Stefanie",
        "local_time_de": current.strftime("%H:%M"),
        "weekday_de": WEEKDAYS_DE[current.weekday()],
        "caller_area_hint": caller_area_hint(from_number),
        "agent_shift_anchor": _shift_anchor(anchor_index),
        "context_priming_rule": (
            "You may casually use agent_shift_anchor once if it fits. "
            "Never use it during emergency triage, never invent facts, and never mention it if the caller is distressed."
        ),
    }


def caller_area_hint(phone_number: str) -> str:
    digits = "".join(ch for ch in str(phone_number) if ch.isdigit())
    if digits.startswith("4915") or digits.startswith("4916") or digits.startswith("4917"):
        return "Deutschland / Mobilfunk"
    if digits.startswith("4930"):
        return "Berlin"
    if digits.startswith("4989"):
        return "Bayern / Muenchen"
    if digits.startswith("4940"):
        return "Hamburg"
    if digits.startswith("49221"):
        return "Nordrhein-Westfalen / Köln"
    if digits.startswith("4969"):
        return "Hessen / Frankfurt am Main"
    if digits.startswith("49"):
        return "Deutschland"
    return "Unknown caller region"


class CallContextStore:
    def __init__(self, trace_root: str | Path = "traces") -> None:
        self.trace_root = Path(trace_root)
        self.cache_path = self.trace_root / "call_context_cache.jsonl"
        self._cache: dict[str, dict[str, Any]] = {}

    def mark_pending(self, call_sid: str, **context: Any) -> None:
        self._set(
            call_sid,
            {
                "ok": True,
                "still_checking": True,
                "updated_at": now_iso(),
                "context": {
                    **context,
                    "web_context": None,
                    "uncertainty": "background_context_not_ready",
                },
            },
        )

    def set_ready(self, call_sid: str, context: dict[str, Any]) -> None:
        self._set(
            call_sid,
            {
                "ok": True,
                "still_checking": False,
                "updated_at": now_iso(),
                "context": context,
            },
        )

    def get_tool_response(self, call_sid: str | None) -> dict[str, Any]:
        key = str(call_sid or "").strip()
        if key and key in self._cache:
            return self._cache[key]
        return {
            "ok": True,
            "still_checking": True,
            "updated_at": now_iso(),
            "context": {
                "answer": "I'm still checking that context. Continue with the caller's own description for now.",
                "uncertainty": "not_ready_or_unknown_call",
            },
        }

    def _set(self, call_sid: str, payload: dict[str, Any]) -> None:
        key = str(call_sid or "").strip() or "unknown-call"
        payload = {"twilio_call_sid": key, **payload}
        self._cache[key] = payload
        self.trace_root.mkdir(parents=True, exist_ok=True)
        with self.cache_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(json_safe(payload), ensure_ascii=False) + "\n")


async def enrich_call_context(
    settings: Settings,
    *,
    store: CallContextStore,
    call_sid: str,
    caller_number: str,
    called_number: str,
    search_func: SearchFunc | None = None,
) -> None:
    area_hint = caller_area_hint(caller_number)
    base_context: dict[str, Any] = {
        "caller_area_hint": area_hint,
        "called_number": called_number,
        "web_context": None,
        "uncertainty": "no_live_context_search_configured",
    }
    store.mark_pending(call_sid, caller_area_hint=area_hint, called_number=called_number)
    if not settings.tavily_api_key:
        store.set_ready(call_sid, base_context)
        return

    search = search_func or _default_search
    try:
        result = search(
            settings,
            query=_broad_context_query(area_hint),
            location=area_hint if area_hint != "Unknown caller region" else None,
            incident_time="today",
        )
        if inspect.isawaitable(result):
            result = await result
        base_context["web_context"] = result
        base_context["uncertainty"] = result.get("uncertainty", "web_context_may_be_incomplete_confirm_with_caller")
    except Exception as exc:
        base_context["web_context"] = {
            "ok": False,
            "answer": "Background context lookup failed. Continue with the caller's own description.",
            "results": [],
            "uncertainty": "background_context_failed",
            "error": str(exc),
        }
        base_context["uncertainty"] = "background_context_failed"
    store.set_ready(call_sid, base_context)


def start_call_context_enrichment(
    settings: Settings,
    *,
    store: CallContextStore,
    call_sid: str,
    caller_number: str,
    called_number: str,
) -> asyncio.Task[None] | None:
    try:
        return asyncio.create_task(
            enrich_call_context(
                settings,
                store=store,
                call_sid=call_sid,
                caller_number=caller_number,
                called_number=called_number,
            )
        )
    except RuntimeError:
        return None


async def _default_search(settings: Settings, **kwargs: Any) -> dict[str, Any]:
    return await asyncio.to_thread(search_claim_context, settings, **kwargs)


def _broad_context_query(area_hint: str) -> str:
    if area_hint and area_hint not in {"Unknown caller region", "Deutschland / Mobilfunk", "Deutschland"}:
        return f"traffic weather roadworks {area_hint} today"
    return "traffic weather roadworks Germany today"


def _shift_anchor(anchor_index: int | None = None) -> str:
    if anchor_index is not None:
        return APPROVED_SHIFT_ANCHORS[anchor_index % len(APPROVED_SHIFT_ANCHORS)]
    return random.choice(APPROVED_SHIFT_ANCHORS)
