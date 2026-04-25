import inspect
import random
import time
from pathlib import Path

from livekit.agents import RunContext


FALLBACK_STALLING_PHRASES = (
    "okay, lemme pull that up",
    "one sec",
    "alright, give me just a moment",
    "let me check that for you, hold on",
    "okay so, let me see",
    "yeah, hang on a sec",
    "alright, pulling that up now",
    "okay, pulling up your file",
)


def _load_generic_stalling_phrases() -> tuple[str, ...]:
    path = Path("prompts/stalling.md")
    if not path.exists():
        return FALLBACK_STALLING_PHRASES

    phrases: list[str] = []
    in_generic_section = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_generic_section = stripped == "## Generic stalling (any lookup)"
            continue
        if in_generic_section and stripped.startswith("- "):
            phrase = stripped[2:].strip()
            if phrase and "<" not in phrase:
                phrases.append(phrase)

    return tuple(phrases) or FALLBACK_STALLING_PHRASES


async def say_stalling_phrase(context: RunContext) -> str:
    phrase = random.choice(_load_generic_stalling_phrases())
    setattr(context.session, "_inca_tool_stalling_until", time.monotonic() + 1.5)
    speech = context.session.say(
        phrase,
        allow_interruptions=True,
        add_to_chat_ctx=True,
    )
    if inspect.isawaitable(speech):
        await speech

    wait_for_playout = context.wait_for_playout()
    if inspect.isawaitable(wait_for_playout):
        await wait_for_playout

    return phrase
