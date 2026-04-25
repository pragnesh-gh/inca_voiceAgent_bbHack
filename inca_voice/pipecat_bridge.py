from __future__ import annotations

import json
from typing import Any

from .audio import TWILIO_RATE


def pipecat_available() -> bool:
    try:
        import pipecat  # noqa: F401
        from pipecat.serializers.twilio import TwilioFrameSerializer  # noqa: F401
        from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport  # noqa: F401
    except Exception:
        return False
    return True


class PipecatTwilioMediaCodec:
    """Small adapter around Pipecat's Twilio Media Streams serializer."""

    def __init__(self, *, stream_sid: str, call_sid: str | None = None) -> None:
        from pipecat.serializers.twilio import TwilioFrameSerializer

        self.stream_sid = stream_sid
        self.call_sid = call_sid
        self.serializer = TwilioFrameSerializer(
            stream_sid=stream_sid,
            call_sid=call_sid,
            params=TwilioFrameSerializer.InputParams(
                twilio_sample_rate=TWILIO_RATE,
                sample_rate=TWILIO_RATE,
                auto_hang_up=False,
            ),
        )

    async def setup(self) -> None:
        from pipecat.frames.frames import StartFrame

        await self.serializer.setup(
            StartFrame(
                audio_in_sample_rate=TWILIO_RATE,
                audio_out_sample_rate=TWILIO_RATE,
            )
        )

    async def decode_media_to_pcm16_8k(self, message: dict[str, Any]) -> bytes | None:
        frame = await self.serializer.deserialize(json.dumps(message))
        if frame is None:
            return None
        return getattr(frame, "audio", None)

    async def encode_pcm16_8k(self, audio: bytes) -> dict[str, Any]:
        from pipecat.frames.frames import AudioRawFrame

        serialized = await self.serializer.serialize(
            AudioRawFrame(audio=audio, sample_rate=TWILIO_RATE, num_channels=1)
        )
        if not serialized:
            return {}
        return json.loads(serialized)

    async def clear_message(self) -> dict[str, Any]:
        from pipecat.frames.frames import InterruptionFrame

        serialized = await self.serializer.serialize(InterruptionFrame())
        if not serialized:
            return {"event": "clear", "streamSid": self.stream_sid}
        return json.loads(serialized)
