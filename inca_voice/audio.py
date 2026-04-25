from __future__ import annotations

import audioop
import base64
from typing import Any


TWILIO_RATE = 8000
GRADIUM_STT_RATE = 24000
SAMPLE_WIDTH = 2


def decode_mulaw_payload(payload: str) -> bytes:
    return base64.b64decode(payload)


def encode_mulaw_payload(audio: bytes) -> str:
    return base64.b64encode(audio).decode("ascii")


def mulaw_to_pcm16_8k(mulaw: bytes) -> bytes:
    return audioop.ulaw2lin(mulaw, SAMPLE_WIDTH)


def pcm16_8k_to_mulaw(pcm: bytes) -> bytes:
    return audioop.lin2ulaw(pcm, SAMPLE_WIDTH)


def pcm16_8k_to_24k(pcm: bytes) -> bytes:
    converted, _ = audioop.ratecv(
        pcm,
        SAMPLE_WIDTH,
        1,
        TWILIO_RATE,
        GRADIUM_STT_RATE,
        None,
    )
    return converted


class RateConverter:
    def __init__(self, source_rate: int, target_rate: int) -> None:
        self.source_rate = source_rate
        self.target_rate = target_rate
        self._state: Any = None

    def convert(self, pcm: bytes) -> bytes:
        converted, self._state = audioop.ratecv(
            pcm,
            SAMPLE_WIDTH,
            1,
            self.source_rate,
            self.target_rate,
            self._state,
        )
        return converted


def pcm16_to_8k_mulaw(pcm: bytes, source_rate: int) -> bytes:
    if source_rate != TWILIO_RATE:
        pcm, _ = audioop.ratecv(
            pcm,
            SAMPLE_WIDTH,
            1,
            source_rate,
            TWILIO_RATE,
            None,
        )
    return pcm16_8k_to_mulaw(pcm)


def is_loud_mulaw(mulaw: bytes, *, threshold: int = 650) -> bool:
    if not mulaw:
        return False
    pcm = mulaw_to_pcm16_8k(mulaw)
    return is_loud_pcm16(pcm, threshold=threshold)


def is_loud_pcm16(pcm: bytes, *, threshold: int = 650) -> bool:
    if not pcm:
        return False
    return audioop.rms(pcm, SAMPLE_WIDTH) >= threshold


def pcm16_duration_ms(pcm: bytes, *, sample_rate: int = TWILIO_RATE) -> float:
    if not pcm:
        return 0.0
    samples = len(pcm) / SAMPLE_WIDTH
    return samples / sample_rate * 1000
