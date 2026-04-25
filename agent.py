import asyncio
from collections.abc import AsyncIterable
from contextlib import suppress
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import random
import re
import time
import traceback
from typing import Any

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import llm
from livekit.agents import Agent, AgentSession, room_io
from livekit.plugins import ai_coustics, gradium, google
from tools.claim import check_claim_status, file_new_claim
from tools.policy import lookup_policy
from tools.search import search_context

load_dotenv()

AGENT_NAME = os.getenv("LIVEKIT_AGENT_NAME", "inca-claims-agent")
THINKING_FILLERS = ("mm-hmm", "one sec", "yeah", "okay", "hmm")


class SessionTrace:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.started_at = _now_iso()
        self.started_monotonic = time.monotonic()
        self.trace_dir = Path("traces")
        self.transcript_dir = Path("transcripts")
        self.trace_dir.mkdir(exist_ok=True)
        self.transcript_dir.mkdir(exist_ok=True)
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id)
        timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        self.trace_path = self.trace_dir / f"{timestamp}-{safe_id}.jsonl"
        self.transcript_path = self.transcript_dir / f"{timestamp}-{safe_id}.jsonl"
        self._logger = logging.getLogger("inca.trace")
        self._handler = _TraceLogHandler(self)
        logging.getLogger().addHandler(self._handler)
        self.event("session_trace_started", trace_file=str(self.trace_path), transcript_file=str(self.transcript_path))

    def event(self, event_type: str, **fields: Any) -> None:
        payload = {
            "ts": _now_iso(),
            "elapsed_ms": round((time.monotonic() - self.started_monotonic) * 1000, 1),
            "session_id": self.session_id,
            "event": event_type,
            **_safe_json(fields),
        }
        self._write_jsonl(self.trace_path, payload)
        self._logger.debug("trace event %s", event_type)

    def transcript(self, speaker: str, text: str, **fields: Any) -> None:
        payload = {
            "ts": _now_iso(),
            "elapsed_ms": round((time.monotonic() - self.started_monotonic) * 1000, 1),
            "session_id": self.session_id,
            "speaker": speaker,
            "text": text,
            **_safe_json(fields),
        }
        self._write_jsonl(self.transcript_path, payload)
        self.event("transcript_line", speaker=speaker, text=text, **fields)

    def close(self, reason: str | None = None, error: Any = None) -> None:
        self.event("session_trace_closed", reason=reason, error=_format_error(error) if error else None)
        logging.getLogger().removeHandler(self._handler)

    @staticmethod
    def _write_jsonl(path: Path, payload: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


class _TraceLogHandler(logging.Handler):
    def __init__(self, trace: SessionTrace):
        super().__init__(level=logging.DEBUG)
        self.trace = trace

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == "inca.trace":
            return
        payload = {
            "logger": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info))
        self.trace.event("log", **payload)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_safe_json(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if hasattr(value, "model_dump"):
        return _safe_json(value.model_dump(mode="json", exclude_none=True))
    return str(value)


def _format_error(error: Any) -> dict[str, str]:
    return {
        "type": error.__class__.__name__,
        "message": str(error),
    }


def _chat_text(message: llm.ChatMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list | tuple):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif hasattr(item, "text"):
                parts.append(str(item.text))
            else:
                parts.append(str(item))
        return " ".join(part for part in parts if part).strip()
    return str(content)


def attach_tracing(session: AgentSession, trace: SessionTrace) -> None:
    filler_task: asyncio.Task[None] | None = None
    opening_delivered = False

    async def thinking_filler() -> None:
        await asyncio.sleep(0.65)
        if session.agent_state != "thinking" or not opening_delivered:
            return
        if time.monotonic() < getattr(session, "_inca_tool_stalling_until", 0):
            return

        phrase = random.choice(THINKING_FILLERS)
        trace.event("thinking_filler_started", phrase=phrase)
        trace.transcript("assistant_buffer", phrase)
        session.say(phrase, allow_interruptions=True, add_to_chat_ctx=False)

    @session.on("user_input_transcribed")
    def on_user_input_transcribed(event) -> None:
        trace.event(
            "user_input_transcribed",
            text=event.transcript,
            is_final=event.is_final,
            speaker_id=event.speaker_id,
            language=event.language,
        )
        if event.is_final and event.transcript.strip():
            trace.transcript("user", event.transcript, language=event.language)

    @session.on("conversation_item_added")
    def on_conversation_item_added(event) -> None:
        nonlocal opening_delivered
        trace.event("conversation_item_added", item_type=event.item.__class__.__name__)
        if isinstance(event.item, llm.ChatMessage):
            text = _chat_text(event.item)
            trace.event("chat_message", role=event.item.role, text=text)
            if event.item.role == "assistant" and text:
                opening_delivered = True
            if event.item.role in {"assistant", "user"} and text:
                trace.transcript(event.item.role, text)

    @session.on("agent_state_changed")
    def on_agent_state_changed(event) -> None:
        nonlocal filler_task
        trace.event("agent_state_changed", old_state=event.old_state, new_state=event.new_state)
        if event.new_state == "thinking":
            if filler_task and not filler_task.done():
                filler_task.cancel()
            filler_task = asyncio.create_task(thinking_filler())
        elif filler_task and not filler_task.done():
            filler_task.cancel()

    @session.on("user_state_changed")
    def on_user_state_changed(event) -> None:
        trace.event("user_state_changed", old_state=event.old_state, new_state=event.new_state)

    @session.on("speech_created")
    def on_speech_created(event) -> None:
        trace.event("speech_created", source=event.source, user_initiated=event.user_initiated)

    @session.on("function_tools_executed")
    def on_function_tools_executed(event) -> None:
        calls = [call.name for call in event.function_calls]
        outputs = [
            {"is_error": getattr(output, "is_error", None), "output": getattr(output, "output", None)}
            for output in event.function_call_outputs
        ]
        trace.event("function_tools_executed", calls=calls, outputs=outputs)

    @session.on("error")
    def on_error(event) -> None:
        trace.event("session_error", source=event.source.__class__.__name__, error=_format_error(event.error))

    @session.on("close")
    def on_close(event) -> None:
        if filler_task and not filler_task.done():
            filler_task.cancel()
        trace.close(reason=str(event.reason), error=event.error)


async def strip_speech_markup(text: AsyncIterable[str]) -> AsyncIterable[str]:
    buffer = ""

    async for chunk in text:
        buffer += chunk
        last_open_tag = buffer.rfind("<")
        last_close_tag = buffer.rfind(">")

        if last_open_tag > last_close_tag:
            ready, buffer = buffer[:last_open_tag], buffer[last_open_tag:]
        else:
            ready, buffer = buffer, ""

        if ready:
            yield re.sub(r"\s*<(?:break|flush)\b[^>]*>\s*", " ", ready)

    if buffer:
        yield re.sub(r"\s*<(?:break|flush)\b[^>]*>\s*", " ", buffer)


class ClaimsAgent(Agent):
    def __init__(self):
        with open("prompts/system.md") as f:
            instructions = f.read()
        with open("prompts/fewshot.md") as f:
            fewshot = f.read().strip()
        if fewshot:
            instructions = f"{instructions}\n\n## Examples of how you talk\n\n{fewshot}"
        super().__init__(
            instructions=instructions,
            tools=[
                lookup_policy,
                check_claim_status,
                file_new_claim,
                search_context,
            ],
        )

async def entrypoint(ctx: agents.JobContext):
    job_id = getattr(ctx.job, "id", "unknown-job")
    room_name = getattr(ctx.room, "name", "unknown-room")
    trace = SessionTrace(f"{room_name}-{job_id}")
    trace.event("entrypoint_started", room=room_name, job_id=job_id)

    session = AgentSession(
        stt=gradium.STT(
            model_endpoint="wss://eu.api.gradium.ai/api/speech/asr",
            temperature=0.0,
        ),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=gradium.TTS(
            model_endpoint="wss://eu.api.gradium.ai/api/speech/tts",
            voice_id=os.getenv("GRADIUM_TTS_VOICE_ID") or "YTpq7expH9539ERJ",
            json_config={
                "padding_bonus": -2.0,
            },
        ),
        vad=ai_coustics.VAD(),
        preemptive_generation=True,
        tts_text_transforms=[
            "filter_markdown",
            "filter_emoji",
            strip_speech_markup,
        ],
    )
    attach_tracing(session, trace)
    trace.event("agent_session_configured")
    await session.start(
        agent=ClaimsAgent(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_L,
                    model_parameters=ai_coustics.ModelParameters(
                        enhancement_level=0.8,
                    ),
                    vad_settings=ai_coustics.VadSettings(
                        speech_hold_duration=0.03,
                        sensitivity=6.0,
                        minimum_speech_duration=0.0,
                    ),
                ),
            ),
        ),
    )
    trace.event("agent_session_started")
    await session.generate_reply(
        instructions="Use one neutral claims-desk opening. Ask how you can help today. Do not assume distress unless the caller reports an accident, injury, unsafe location, panic, or confusion. Do not describe your thinking."
    )

if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(entrypoint_fnc=entrypoint, agent_name=AGENT_NAME)
    )
