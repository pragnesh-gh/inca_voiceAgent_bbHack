from __future__ import annotations

import asyncio
import json
import random
import traceback
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from .audio import (
    decode_mulaw_payload,
    encode_mulaw_payload,
    is_loud_pcm16,
    mulaw_to_pcm16_8k,
    pcm16_duration_ms,
)
from .config import Settings, load_settings
from .elevenlabs_runtime import (
    build_claim_from_post_call_webhook,
    elevenlabs_ready,
    register_elevenlabs_call,
    verify_or_parse_elevenlabs_webhook,
)
from .gemini_agent import ClaimsResponder
from .gradium import GradiumSTT, GradiumTTS
from .noise import NoiseEnhancer
from .pipecat_bridge import PipecatTwilioMediaCodec, pipecat_available
from .scribe import ClaimsScribe
from .tracing import CallTrace
from .turns import CommittedTurn, TurnManager, TurnSettings


load_dotenv()
app = FastAPI(title="Inca Twilio Media Streams Agent")


OPENINGS = (
    "Meridian Mutual claims, Stefanie speaking. How can I help today?",
    "Claims desk, this is Stefanie at Meridian Mutual. What's going on today?",
    "Meridian Mutual, Stefanie speaking. Tell me what I can help with.",
)

FILLERS = ("mm-hmm", "one sec", "okay", "yeah, one moment")


@app.get("/health")
async def health() -> dict[str, Any]:
    settings = load_settings()
    return {
        "ok": True,
        "twilio_phone_number_set": bool(settings.twilio_phone_number),
        "gradium_key_set": bool(settings.gradium_api_key),
        "google_key_set": bool(settings.google_api_key),
        "aicoustics_key_set": bool(settings.aicoustics_api_key),
        "primary_model": settings.gemini_primary_model,
        "fallback_model": settings.gemini_fallback_model,
        "pipecat_available": pipecat_available(),
        "use_pipecat_runtime": settings.use_pipecat_runtime,
        "use_legacy_twilio_loop": settings.use_legacy_twilio_loop,
        "use_elevenlabs_register_call": settings.use_elevenlabs_register_call,
        "elevenlabs_key_set": bool(settings.elevenlabs_api_key),
        "elevenlabs_agent_id_set": bool(settings.elevenlabs_agent_id),
    }


@app.api_route("/twilio/voice", methods=["GET", "POST"])
async def twilio_voice(request: Request) -> Response:
    settings = load_settings()
    form = await _read_twilio_form(request)
    call_sid = str(form.get("CallSid") or "")
    from_number = str(form.get("From") or "unknown")
    to_number = str(form.get("To") or settings.twilio_phone_number or "unknown")
    if settings.use_elevenlabs_register_call:
        try:
            if not elevenlabs_ready(settings):
                raise RuntimeError("ElevenLabs register-call runtime is enabled but ELEVENLABS_API_KEY or ELEVENLABS_AGENT_ID is missing")
            twiml = register_elevenlabs_call(
                settings,
                from_number=from_number,
                to_number=to_number,
                call_sid=call_sid,
            )
            print(
                "ElevenLabs register_call succeeded "
                f"call_sid={call_sid or 'missing'} from={redacted(from_number)} to={redacted(to_number)} "
                f"twiml_chars={len(twiml)}",
                flush=True,
            )
            return Response(content=twiml, media_type="application/xml")
        except Exception as exc:
            print(f"ElevenLabs register_call failed; falling back to local Twilio stream: {exc}", flush=True)
            traceback.print_exc()
    stream_url = _stream_url(request, settings)
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="{escape(stream_url)}">'
        f'<Parameter name="call_sid" value="{escape(call_sid)}" />'
        "</Stream>"
        "</Connect>"
        "</Response>"
    )
    return Response(content=twiml, media_type="application/xml")


@app.post("/elevenlabs/post-call")
async def elevenlabs_post_call(request: Request) -> JSONResponse:
    settings = load_settings()
    raw_body = (await request.body()).decode("utf-8", errors="replace")
    signature = request.headers.get("ElevenLabs-Signature")
    try:
        payload = verify_or_parse_elevenlabs_webhook(raw_body, signature, settings)
        result = await build_claim_from_post_call_webhook(payload, settings)
        return JSONResponse({"ok": True, "conversation_id": result["conversation_id"], "trace_dir": result["trace_dir"]})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


async def _read_twilio_form(request: Request) -> dict[str, str]:
    if request.method != "POST":
        return {}
    body = (await request.body()).decode("utf-8", errors="replace")
    parsed = parse_qs(body)
    return {key: values[0] for key, values in parsed.items() if values}


@app.websocket("/twilio/media")
async def twilio_media(websocket: WebSocket) -> None:
    settings = load_settings()
    await websocket.accept()
    session = TwilioMediaSession(websocket, settings)
    await session.run()


class TwilioMediaSession:
    def __init__(self, websocket: WebSocket, settings: Settings) -> None:
        self.websocket = websocket
        self.settings = settings
        self.stream_sid: str | None = None
        self.call_sid = "unknown-call"
        self.trace: CallTrace | None = None
        self.tts: GradiumTTS | None = None
        self.stt: GradiumSTT | None = None
        self.responder: ClaimsResponder | None = None
        self.scribe: ClaimsScribe | None = None
        self.enhancer: NoiseEnhancer | None = None
        self.codec: PipecatTwilioMediaCodec | None = None
        self.turn_manager = TurnManager(
            TurnSettings(
                min_words=settings.turn_min_words,
                min_chars=settings.turn_min_chars,
                settle_ms=settings.turn_settle_ms,
                max_wait_ms=settings.turn_max_wait_ms,
            )
        )
        self.turn_task: asyncio.Task[None] | None = None
        self.background_tasks: set[asyncio.Task[Any]] = set()
        self.pending_marks: set[str] = set()
        self.mark_counter = 0
        self.barge_in_loud_ms = 0.0
        self.respond_lock = asyncio.Lock()
        self.speaking = False
        self.closed = False

    async def run(self) -> None:
        try:
            while True:
                raw = await self.websocket.receive_text()
                message = json.loads(raw)
                await self._handle_message(message)
        except WebSocketDisconnect:
            await self._close("websocket_disconnect")
        except Exception as exc:
            if self.trace:
                self.trace.error("twilio_media", exc)
            await self._close("error")

    async def _handle_message(self, message: dict[str, Any]) -> None:
        event = message.get("event")
        if event == "connected":
            return
        if event == "start":
            await self._start(message)
            return
        if event == "media":
            await self._media(message)
            return
        if event == "mark":
            await self._handle_mark(message)
            return
        if event == "dtmf" and self.trace:
            self.trace.event("twilio_dtmf", dtmf=message.get("dtmf"))
            return
        if event == "stop":
            await self._close("twilio_stop")

    async def _start(self, message: dict[str, Any]) -> None:
        start = message.get("start") or {}
        self.stream_sid = start.get("streamSid") or message.get("streamSid")
        self.call_sid = start.get("callSid") or self._custom_parameter(start, "call_sid") or "unknown-call"
        self.trace = CallTrace(self.call_sid, trace_root=self.settings.trace_dir)
        self.trace.event(
            "twilio_start",
            stream_sid=self.stream_sid,
            account_sid=redacted(start.get("accountSid")),
            media_format=start.get("mediaFormat"),
            custom_parameters=start.get("customParameters"),
        )
        await self._setup_pipecat_codec()
        self.tts = GradiumTTS(self.settings, self.trace)
        self.enhancer = NoiseEnhancer(self.settings, self.trace)
        self.scribe = ClaimsScribe(self.settings, self.trace)
        self.responder = ClaimsResponder(self.settings, self.trace)
        self.stt = GradiumSTT(
            self.settings,
            self.trace,
            self.enhancer,
            self._on_transcript,
        )
        try:
            await self.stt.start()
        except Exception as exc:
            self.trace.error("stt_start", exc)
        await self.say(random.choice(OPENINGS))

    async def _setup_pipecat_codec(self) -> None:
        if not self.stream_sid or self.settings.use_legacy_twilio_loop or not self.settings.use_pipecat_runtime:
            return
        if not pipecat_available():
            self.trace.event("pipecat_codec_unavailable")
            return
        try:
            self.codec = PipecatTwilioMediaCodec(stream_sid=self.stream_sid, call_sid=self.call_sid)
            await self.codec.setup()
            self.trace.event("pipecat_codec_enabled", stream_sid=self.stream_sid)
        except Exception as exc:
            self.codec = None
            self.trace.error("pipecat_codec_setup", exc)

    async def _media(self, message: dict[str, Any]) -> None:
        media = message.get("media") or {}
        payload = media.get("payload")
        if not payload:
            return
        pcm_8k = await self._media_pcm16_8k(message, payload)
        if self.speaking and pcm_8k:
            if is_loud_pcm16(pcm_8k):
                self.barge_in_loud_ms += pcm16_duration_ms(pcm_8k)
                if self.barge_in_loud_ms >= self.settings.barge_in_min_ms:
                    if self.trace:
                        self.trace.event("barge_in", loud_ms=self.barge_in_loud_ms)
                    await self.clear_audio("caller_barge_in")
                    self.barge_in_loud_ms = 0.0
            else:
                self.barge_in_loud_ms = 0.0
        if self.stt:
            if pcm_8k:
                await self.stt.send_pcm16_8k(pcm_8k)
            else:
                await self.stt.send_twilio_media(payload)

    async def _media_pcm16_8k(self, message: dict[str, Any], payload: str) -> bytes | None:
        if self.codec:
            try:
                return await self.codec.decode_media_to_pcm16_8k(message)
            except Exception as exc:
                if self.trace:
                    self.trace.error("pipecat_decode_media", exc)
        return mulaw_to_pcm16_8k(decode_mulaw_payload(payload))

    async def _on_transcript(self, text: str, metadata: dict[str, Any]) -> None:
        if self.closed or not self.trace or not self.scribe:
            return
        self.trace.event("user_transcript_fragment", text=text, metadata=metadata)
        turns = self.turn_manager.add_fragment(
            text,
            now_ms=self.trace.elapsed_ms,
            metadata=metadata,
        )
        for turn in turns:
            await self._commit_turn(turn)
        self._schedule_turn_drain()

    def _schedule_turn_drain(self) -> None:
        if self.closed:
            return
        if self.turn_task and not self.turn_task.done():
            self.turn_task.cancel()
        self.turn_task = asyncio.create_task(self._drain_turns_when_ready())

    async def _drain_turns_when_ready(self) -> None:
        try:
            while not self.closed and self.turn_manager.pending_text:
                await asyncio.sleep(max(self.settings.turn_settle_ms, 50) / 1000)
                if not self.trace:
                    return
                turns = self.turn_manager.drain_ready(now_ms=self.trace.elapsed_ms)
                for turn in turns:
                    await self._commit_turn(turn)
                if turns or not self.turn_manager.pending_text:
                    return
        except asyncio.CancelledError:
            return

    async def _commit_turn(self, turn: CommittedTurn) -> None:
        if self.closed or not self.trace or not self.scribe:
            return
        print(f"USER TURN: {turn.text}", flush=True)
        self.trace.event("turn_committed", text=turn.text, metadata=turn.metadata)
        self.trace.transcript("user", turn.text, **turn.metadata)
        self._track_task(self._record_scribe_turn("user", turn.text))
        self._track_task(self._respond(turn.text))

    async def _respond(self, user_text: str) -> None:
        async with self.respond_lock:
            if self.closed or not self.responder or not self.scribe or not self.trace:
                return
            filler = asyncio.create_task(self._delayed_filler())
            started_ms = self.trace.elapsed_ms
            response = await self.responder.reply(user_text, self.scribe.state)
            self.trace.event("llm_latency_ms", elapsed_ms=self.trace.elapsed_ms - started_ms)
            filler.cancel()
            with suppress_asyncio_cancelled():
                await filler
            if self.closed:
                return
            self._track_task(self._record_scribe_turn("assistant", response))
            await self.say(response)

    async def _record_scribe_turn(self, speaker: str, text: str) -> None:
        if not self.scribe or not self.trace:
            return
        try:
            await self.scribe.record_turn(speaker, text)
        except Exception as exc:
            self.trace.error("scribe_record_turn", exc, speaker=speaker, text=text)

    def _track_task(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def _delayed_filler(self) -> None:
        await asyncio.sleep(0.75)
        if not self.closed:
            await self.say(random.choice(FILLERS), speaker="assistant_buffer")

    async def say(self, text: str, *, speaker: str = "assistant") -> None:
        if self.closed or not self.stream_sid or not self.tts or not self.trace:
            return
        self.trace.transcript(speaker, text)
        self.speaking = True
        self.mark_counter += 1
        mark_name = f"played-{speaker}-{self.mark_counter}"
        self.pending_marks.add(mark_name)
        started_ms = self.trace.elapsed_ms
        sent_any = False
        try:
            if self.codec:
                async for chunk in self.tts.synthesize_pcm16_8k(text):
                    if self.closed:
                        return
                    message = await self.codec.encode_pcm16_8k(chunk)
                    if message:
                        await self.websocket.send_json(message)
                        if not sent_any:
                            self.trace.event(
                                "tts_first_audio_ms",
                                speaker=speaker,
                                elapsed_ms=self.trace.elapsed_ms - started_ms,
                            )
                            sent_any = True
            else:
                async for chunk in self.tts.synthesize_ulaw(text):
                    if self.closed:
                        return
                    await self.websocket.send_json(
                        {
                            "event": "media",
                            "streamSid": self.stream_sid,
                            "media": {"payload": encode_mulaw_payload(chunk)},
                        }
                    )
                    if not sent_any:
                        self.trace.event(
                            "tts_first_audio_ms",
                            speaker=speaker,
                            elapsed_ms=self.trace.elapsed_ms - started_ms,
                        )
                        sent_any = True
            await self.websocket.send_json(
                {
                    "event": "mark",
                    "streamSid": self.stream_sid,
                    "mark": {"name": mark_name},
                }
            )
        except Exception as exc:
            self.pending_marks.discard(mark_name)
            self.speaking = bool(self.pending_marks)
            self.trace.error("say", exc, text=text)

    async def clear_audio(self, reason: str) -> None:
        if self.closed or not self.stream_sid:
            return
        if self.trace:
            self.trace.event("twilio_clear", reason=reason)
        message = await self.codec.clear_message() if self.codec else {"event": "clear", "streamSid": self.stream_sid}
        await self.websocket.send_json(message)
        self.pending_marks.clear()
        self.speaking = False

    async def _close(self, reason: str) -> None:
        if self.closed:
            return
        self.closed = True
        if self.turn_task and not self.turn_task.done():
            self.turn_task.cancel()
        for task in list(self.background_tasks):
            task.cancel()
        if self.trace:
            self.trace.event("session_closing", reason=reason)
        if self.stt:
            await self.stt.stop()
        if self.scribe:
            await self.scribe.close()
        if self.trace:
            self.trace.event("session_closed", reason=reason)

    async def _handle_mark(self, message: dict[str, Any]) -> None:
        mark = message.get("mark") or {}
        name = mark.get("name")
        if name:
            self.pending_marks.discard(str(name))
        self.speaking = bool(self.pending_marks)
        if self.trace:
            self.trace.event("playback_mark", mark=mark, pending_marks=len(self.pending_marks))

    @staticmethod
    def _custom_parameter(start: dict[str, Any], name: str) -> str | None:
        params = start.get("customParameters") or {}
        value = params.get(name)
        return str(value) if value else None


def _stream_url(request: Request, settings: Settings) -> str:
    if settings.public_base_url:
        base = settings.public_base_url.rstrip("/")
        parsed = urlparse(base)
        scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
        return f"{scheme}://{parsed.netloc}/twilio/media"

    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    scheme = "wss" if proto in {"https", "wss"} or "localhost" not in host else "ws"
    return f"{scheme}://{host}/twilio/media"


def redacted(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    return text[:4] + "..." + text[-4:] if len(text) > 8 else "***"


class suppress_asyncio_cancelled:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is asyncio.CancelledError
