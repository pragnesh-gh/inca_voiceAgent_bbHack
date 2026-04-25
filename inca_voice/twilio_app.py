from __future__ import annotations

import asyncio
import json
import random
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from .audio import decode_mulaw_payload, encode_mulaw_payload, is_loud_mulaw
from .config import Settings, load_settings
from .gemini_agent import ClaimsResponder
from .gradium import GradiumSTT, GradiumTTS
from .noise import NoiseEnhancer
from .scribe import ClaimsScribe
from .tracing import CallTrace


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
    }


@app.api_route("/twilio/voice", methods=["GET", "POST"])
async def twilio_voice(request: Request) -> Response:
    settings = load_settings()
    form = await _read_twilio_form(request)
    call_sid = str(form.get("CallSid") or "")
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
    return Response(content=twiml, media_type="text/xml")


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
        if event == "mark" and self.trace:
            self.trace.event("twilio_mark", mark=message.get("mark"))
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

    async def _media(self, message: dict[str, Any]) -> None:
        media = message.get("media") or {}
        payload = media.get("payload")
        if not payload:
            return
        if self.speaking and is_loud_mulaw(decode_mulaw_payload(payload)):
            await self.clear_audio("caller_barge_in")
        if self.stt:
            await self.stt.send_twilio_media(payload)

    async def _on_transcript(self, text: str, metadata: dict[str, Any]) -> None:
        if not self.trace or not self.scribe:
            return
        self.trace.event("user_transcript_final", text=text, metadata=metadata)
        self.trace.transcript("user", text, **metadata)
        await self.scribe.record_turn("user", text)
        asyncio.create_task(self._respond(text))

    async def _respond(self, user_text: str) -> None:
        async with self.respond_lock:
            if not self.responder or not self.scribe:
                return
            filler = asyncio.create_task(self._delayed_filler())
            response = await self.responder.reply(user_text, self.scribe.state)
            filler.cancel()
            with suppress_asyncio_cancelled():
                await filler
            await self.scribe.record_turn("assistant", response)
            await self.say(response)

    async def _delayed_filler(self) -> None:
        await asyncio.sleep(0.75)
        await self.say(random.choice(FILLERS), speaker="assistant_buffer")

    async def say(self, text: str, *, speaker: str = "assistant") -> None:
        if not self.stream_sid or not self.tts or not self.trace:
            return
        self.trace.transcript(speaker, text)
        self.speaking = True
        try:
            async for chunk in self.tts.synthesize_ulaw(text):
                await self.websocket.send_json(
                    {
                        "event": "media",
                        "streamSid": self.stream_sid,
                        "media": {"payload": encode_mulaw_payload(chunk)},
                    }
                )
            await self.websocket.send_json(
                {
                    "event": "mark",
                    "streamSid": self.stream_sid,
                    "mark": {"name": f"played-{speaker}"},
                }
            )
        except Exception as exc:
            self.trace.error("say", exc, text=text)
        finally:
            self.speaking = False

    async def clear_audio(self, reason: str) -> None:
        if not self.stream_sid:
            return
        if self.trace:
            self.trace.event("twilio_clear", reason=reason)
        await self.websocket.send_json({"event": "clear", "streamSid": self.stream_sid})
        self.speaking = False

    async def _close(self, reason: str) -> None:
        if self.closed:
            return
        self.closed = True
        if self.trace:
            self.trace.event("session_closing", reason=reason)
        if self.stt:
            await self.stt.stop()
        if self.scribe:
            await self.scribe.close()
        if self.trace:
            self.trace.event("session_closed", reason=reason)

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
