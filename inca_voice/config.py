from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    twilio_phone_number: str | None
    public_base_url: str | None
    google_api_key: str | None
    gemini_primary_model: str
    gemini_fallback_model: str
    gradium_api_key: str | None
    gradium_asr_url: str
    gradium_tts_url: str
    gradium_stt_model: str
    gradium_tts_model: str
    gradium_voice_id: str
    aicoustics_api_key: str | None
    enable_aicoustics: bool
    trace_dir: str
    vad_end_threshold: float


def load_settings() -> Settings:
    gradium_asr = _env_first(
        "GRADIUM_ASR_ENDPOINT",
        default="wss://api.gradium.ai/api/speech/asr",
    )
    gradium_tts = _env_first(
        "GRADIUM_TTS_ENDPOINT",
        default=gradium_asr.replace("/asr", "/tts"),
    )
    return Settings(
        twilio_phone_number=_env_first("TWILIO_PHONE_NUMBER"),
        public_base_url=_env_first("PUBLIC_BASE_URL", "PUBLIC_URL"),
        google_api_key=_env_first("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        gemini_primary_model=_env_first(
            "GEMINI_PRIMARY_MODEL",
            default="gemini-3-flash-preview",
        ),
        gemini_fallback_model=_env_first(
            "GEMINI_FALLBACK_MODEL",
            default="gemini-2.5-flash",
        ),
        gradium_api_key=_env_first("GRADIUM_API_KEY"),
        gradium_asr_url=gradium_asr,
        gradium_tts_url=gradium_tts,
        gradium_stt_model=_env_first("GRADIUM_STT_MODEL", default="default"),
        gradium_tts_model=_env_first("GRADIUM_TTS_MODEL", default="default"),
        gradium_voice_id=_env_first(
            "GRADIUM_TTS_VOICE_ID",
            default="YTpq7expH9539ERJ",
        ),
        aicoustics_api_key=_env_first("AICOUSTICS_API_KEY", "AIC_SDK_LICENSE"),
        enable_aicoustics=_env_bool("ENABLE_AICOUSTICS", default=True),
        trace_dir=_env_first("TRACE_DIR", default="traces"),
        vad_end_threshold=float(_env_first("GRADIUM_VAD_END_THRESHOLD", default="0.55")),
    )


def _env_first(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip().strip('"').strip("'")
    return default


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}
