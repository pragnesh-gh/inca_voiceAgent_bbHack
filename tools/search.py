import os
from typing import Any

from livekit.agents import RunContext, function_tool
from tools.stalling import say_stalling_phrase


@function_tool()
async def search_context(context: RunContext, query: str) -> str:
    """Search outside context for a claim after the caller gives location/date details.

    Args:
        query: A concise web search query with place plus date or time when available.
            Use for weather, road conditions, traffic, events, demonstrations,
            construction, roadworks, or public incidents near the loss location.
    """
    await say_stalling_phrase(context)

    cleaned_query = query.strip()
    if not cleaned_query:
        return "No search query was provided."

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "Search is unavailable because Tavily is not configured."

    try:
        from tavily import AsyncTavilyClient

        client = AsyncTavilyClient(api_key=api_key)
        response: dict[str, Any] = await client.search(
            query=cleaned_query,
            search_depth="basic",
            include_answer=True,
            include_raw_content=False,
            max_results=3,
        )
    except Exception as exc:
        return f"Search is unavailable right now: {exc.__class__.__name__}."

    parts: list[str] = []
    answer = response.get("answer")
    if answer:
        parts.append(str(answer).strip())

    results = response.get("results") or []
    for result in results[:3]:
        title = str(result.get("title") or "").strip()
        content = str(result.get("content") or "").strip()
        url = str(result.get("url") or "").strip()
        if title and content:
            parts.append(f"{title}: {content}")
        elif content:
            parts.append(content)
        elif title:
            parts.append(title)
        if url and parts:
            parts[-1] = f"{parts[-1]} ({url})"

    return "\n".join(parts) if parts else "No useful search results found."
