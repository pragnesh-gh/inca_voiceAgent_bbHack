from __future__ import annotations

import json
from typing import Any, Callable
from urllib import error, request

from .config import Settings


ALLOWED_CONTEXT_TERMS = (
    "weather",
    "rain",
    "snow",
    "ice",
    "fog",
    "visibility",
    "wind",
    "traffic",
    "road",
    "roadworks",
    "construction",
    "closure",
    "closed",
    "highway",
    "autobahn",
    "a100",
    "a10",
    "a2",
    "a3",
    "a4",
    "a5",
    "a6",
    "a7",
    "a8",
    "a9",
    "stau",
    "baustelle",
    "sperrung",
    "unfall",
    "verkehr",
    "demonstration",
    "protest",
    "event",
    "parade",
)

BLOCKED_CONTEXT_TERMS = (
    "coverage",
    "deductible",
    "premium",
    "sf-klasse",
    "schadenfreiheitsklasse",
    "liable",
    "liability",
    "legal advice",
    "lawyer",
    "policy wording",
    "akb",
    "versicherung",
    "claim denied",
    "fraud",
)


def is_allowed_claim_context_query(query: str) -> bool:
    lower = query.casefold()
    if not lower.strip():
        return False
    if any(term in lower for term in BLOCKED_CONTEXT_TERMS):
        return False
    return any(term in lower for term in ALLOWED_CONTEXT_TERMS)


def search_claim_context(
    settings: Settings,
    *,
    query: str,
    location: str | None = None,
    incident_time: str | None = None,
    fetch: Callable[[request.Request, float], bytes] | None = None,
) -> dict[str, Any]:
    normalized_query = build_context_query(query, location=location, incident_time=incident_time)
    if not is_allowed_claim_context_query(normalized_query):
        return {
            "ok": False,
            "allowed": False,
            "query": normalized_query,
            "answer": "I can only check live context like weather, traffic, roadworks, closures, or public events. I cannot use web search for coverage, liability, legal, or policy decisions.",
            "results": [],
            "uncertainty": "not_searched_scope_limited",
        }
    if not settings.tavily_api_key:
        return {
            "ok": False,
            "allowed": True,
            "query": normalized_query,
            "answer": "Live context search is not configured.",
            "results": [],
            "uncertainty": "missing_tavily_api_key",
        }

    payload = {
        "query": normalized_query,
        "search_depth": "basic",
        "max_results": max(1, min(settings.tavily_max_results, 5)),
        "include_answer": "basic",
        "include_raw_content": False,
        "include_images": False,
        "topic": "general",
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        settings.tavily_search_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.tavily_api_key}",
        },
    )
    try:
        raw = fetch(req, 12.0) if fetch else _fetch(req, 12.0)
        data = json.loads(raw.decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return _error_result(normalized_query, f"Tavily HTTP {exc.code}: {detail}")
    except Exception as exc:
        return _error_result(normalized_query, str(exc))

    results = []
    for item in data.get("results", [])[: payload["max_results"]]:
        results.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "content": item.get("content"),
                "score": item.get("score"),
            }
        )
    return {
        "ok": True,
        "allowed": True,
        "query": normalized_query,
        "answer": data.get("answer") or summarize_results(results),
        "results": results,
        "uncertainty": "web_context_may_be_incomplete_confirm_with_caller",
    }


def build_context_query(query: str, *, location: str | None, incident_time: str | None) -> str:
    parts = [query.strip()]
    if location:
        parts.append(str(location).strip())
    if incident_time:
        parts.append(str(incident_time).strip())
    return " ".join(part for part in parts if part)


def summarize_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return "No useful live context found."
    first = results[0]
    title = first.get("title") or "Result"
    content = first.get("content") or ""
    return f"{title}: {content[:240]}"


def _fetch(req: request.Request, timeout: float) -> bytes:
    with request.urlopen(req, timeout=timeout) as response:
        return response.read()


def _error_result(query: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "allowed": True,
        "query": query,
        "answer": "Live context search failed. Continue with the caller's own description.",
        "results": [],
        "uncertainty": "search_error",
        "error": message,
    }
