from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from time import monotonic
from typing import Any

import websockets

from .audio import GRADIUM_STT_RATE, TWILIO_RATE, RateConverter, decode_mulaw_payload, mulaw_to_pcm16_8k
from .config import Settings
from .noise import NoiseEnhancer


TranscriptCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class GradiumError(RuntimeError):
    pass


async def _connect(url: str, api_key: str):
    headers = {"x-api-key": api_key}
    try:
        return await websockets.connect(url, additional_headers=headers)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers)


class GradiumTTS:
    def __init__(self, settings: Settings, trace: Any) -> None:
        self.settings = settings
        self.trace = trace

    async def synthesize_ulaw(self, text: str) -> AsyncIterator[bytes]:
        if not self.settings.gradium_api_key:
            self.trace.error("gradium_tts", "GRADIUM_API_KEY is missing")
            return

        websocket = await _connect(self.settings.gradium_tts_url, self.settings.gradium_api_key)
        try:
            await websocket.send(
                json.dumps(
                    {
                        "type": "setup",
                        "model_name": self.settings.gradium_tts_model,
                        "voice_id": self.settings.gradium_voice_id,
                        "output_format": "ulaw_8000",
                    }
                )
            )
            ready = json.loads(await websocket.recv())
            if ready.get("type") != "ready":
                raise GradiumError(f"TTS setup failed: {ready}")

            await websocket.send(json.dumps({"type": "text", "text": clean_tts_text(text)}))
            await websocket.send(json.dumps({"type": "end_of_stream"}))

            while True:
                message = json.loads(await websocket.recv())
                msg_type = message.get("type")
                if msg_type == "audio":
                    yield base64.b64decode(message["audio"])
                elif msg_type == "error":
                    raise GradiumError(message.get("message", "Gradium TTS error"))
                elif msg_type == "end_of_stream":
                    break
        finally:
            await websocket.close()


class GradiumSTT:
    def __init__(
        self,
        settings: Settings,
        trace: Any,
        enhancer: NoiseEnhancer,
        on_transcript: TranscriptCallback,
    ) -> None:
        self.settings = settings
        self.trace = trace
        self.enhancer = enhancer
        self.on_transcript = on_transcript
        self._websocket: Any = None
        self._receiver: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._buffer = bytearray()
        self._resampler = RateConverter(TWILIO_RATE, GRADIUM_STT_RATE)
        self._current_text = ""
        self._last_emit = ""
        self._last_emit_at = 0.0
        self._flush_id = 0

    async def start(self) -> None:
        if not self.settings.gradium_api_key:
            self.trace.error("gradium_stt", "GRADIUM_API_KEY is missing")
            return
        self._websocket = await _connect(
            self.settings.gradium_asr_url,
            self.settings.gradium_api_key,
        )
        await self._websocket.send(
            json.dumps(
                {
                    "type": "setup",
                    "model_name": self.settings.gradium_stt_model,
                    "input_format": "pcm",
                }
            )
        )
        self._receiver = asyncio.create_task(self._receive_loop())
        await asyncio.wait_for(self._ready.wait(), timeout=8)

    async def send_twilio_media(self, payload: str) -> None:
        if not self._websocket or not self._ready.is_set():
            return
        mulaw = decode_mulaw_payload(payload)
        pcm_8k = mulaw_to_pcm16_8k(mulaw)
        pcm_8k = self.enhancer.enhance_pcm16_8k(pcm_8k)
        pcm_24k = self._resampler.convert(pcm_8k)
        self._buffer.extend(pcm_24k)
        frame_bytes = 1920 * 2
        while len(self._buffer) >= frame_bytes:
            chunk = bytes(self._buffer[:frame_bytes])
            del self._buffer[:frame_bytes]
            await self._send_audio(chunk)

    async def stop(self) -> None:
        if self._websocket:
            with contextlib_suppress():
                await self._websocket.send(json.dumps({"type": "end_of_stream"}))
            with contextlib_suppress():
                await self._websocket.close()
        if self._receiver:
            self._receiver.cancel()
            with contextlib_suppress():
                await self._receiver

    async def _send_audio(self, pcm: bytes) -> None:
        async with self._send_lock:
            await self._websocket.send(
                json.dumps(
                    {
                        "type": "audio",
                        "audio": base64.b64encode(pcm).decode("ascii"),
                    }
                )
            )

    async def _receive_loop(self) -> None:
        try:
            async for raw in self._websocket:
                message = json.loads(raw)
                msg_type = message.get("type")
                if msg_type == "ready":
                    self.trace.event("gradium_stt_ready", sample_rate=message.get("sample_rate"))
                    self._ready.set()
                elif msg_type == "text":
                    text = str(message.get("text") or "").strip()
                    if text:
                        self._current_text = text
                        self.trace.event("gradium_stt_partial", text=text)
                elif msg_type == "step":
                    await self._maybe_end_turn(message)
                elif msg_type in {"end_text", "flushed"}:
                    await self._emit_current({"reason": msg_type, **message})
                elif msg_type == "error":
                    self.trace.error("gradium_stt", message.get("message", "Gradium STT error"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.trace.error("gradium_stt_receive", exc)

    async def _maybe_end_turn(self, message: dict[str, Any]) -> None:
        vad = message.get("vad") or []
        if len(vad) < 3 or not self._current_text:
            return
        inactivity = float(vad[2].get("inactivity_prob") or 0.0)
        if inactivity < self.settings.vad_end_threshold:
            return
        if monotonic() - self._last_emit_at < 1.0:
            return
        self._flush_id += 1
        with contextlib_suppress():
            await self._websocket.send(
                json.dumps({"type": "flush", "flush_id": str(self._flush_id)})
            )
        await self._emit_current(
            {
                "reason": "vad",
                "inactivity_prob": inactivity,
                "total_duration_s": message.get("total_duration_s"),
            }
        )

    async def _emit_current(self, metadata: dict[str, Any]) -> None:
        text = self._current_text.strip()
        if not text or text == self._last_emit:
            return
        self._last_emit = text
        self._last_emit_at = monotonic()
        self._current_text = ""
        await self.on_transcript(text, metadata)


def clean_tts_text(text: str) -> str:
    cleaned = text.replace("<", " ").replace(">", " ")
    for token in ("```", "*", "#", "- "):
        cleaned = cleaned.replace(token, " ")
    return " ".join(cleaned.split())


class contextlib_suppress:
    def __init__(self, *exceptions: type[BaseException]) -> None:
        self.exceptions = exceptions or (Exception,)

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is not None and issubclass(exc_type, self.exceptions)
