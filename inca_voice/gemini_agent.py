from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from .config import Settings


FALLBACK_REPLY = "Okay, I am with you. Tell me what happened, just the short version first."


class ClaimsResponder:
    def __init__(self, settings: Settings, trace: Any) -> None:
        self.settings = settings
        self.trace = trace
        self.system_prompt = _load_prompt()
        self.history: list[dict[str, str]] = []
        self._client = genai.Client(api_key=settings.google_api_key) if settings.google_api_key else None

    async def reply(self, user_text: str, claim_state: dict[str, Any]) -> str:
        self.history.append({"role": "user", "text": user_text})
        if not self._client:
            self.trace.error("gemini", "GOOGLE_API_KEY is missing")
            return FALLBACK_REPLY

        contents = self._build_contents(user_text, claim_state)
        for model in (self.settings.gemini_primary_model, self.settings.gemini_fallback_model):
            try:
                response = await self._client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        temperature=0.65,
                        max_output_tokens=120,
                        system_instruction=self.system_prompt,
                    ),
                )
                text = sanitize_reply(response.text or "")
                if text:
                    self.history.append({"role": "assistant", "text": text})
                    self.trace.event("gemini_reply", model=model, text=text)
                    return text
            except Exception as exc:
                self.trace.error("gemini_reply", exc, model=model)
                await asyncio.sleep(0.05)
        return FALLBACK_REPLY

    def _build_contents(self, user_text: str, claim_state: dict[str, Any]) -> list[str]:
        recent = self.history[-8:]
        transcript = "\n".join(f"{item['role']}: {item['text']}" for item in recent)
        return [
            "Recent call transcript:\n"
            + transcript
            + "\n\nCurrent structured claim state:\n"
            + str(claim_state)
            + "\n\nReturn only what Stefanie says next on the phone."
        ]


def _load_prompt() -> str:
    parts: list[str] = []
    for path in (Path("prompts/system.md"), Path("prompts/fewshot.md")):
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    parts.append(
        "Critical runtime rules: never reveal reasoning; never output XML, SSML, "
        "Markdown, bullets, or pause tags; keep replies short enough for a phone call."
    )
    return "\n\n".join(parts)


def sanitize_reply(text: str) -> str:
    text = text.strip().replace("\r", " ").replace("\n", " ")
    forbidden = ("<break", "<speak", "</", "```")
    for marker in forbidden:
        text = text.replace(marker, " ")
    text = " ".join(text.split())
    if len(text) > 360:
        text = text[:360].rsplit(" ", 1)[0].strip() + "."
    return text
