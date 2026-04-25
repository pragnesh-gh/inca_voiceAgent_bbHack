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
    gradium_stt_language_hint: str | None
    gradium_stt_delay_in_frames: int | None
    gradium_tts_padding_bonus: float | None
    aicoustics_api_key: str | None
    enable_aicoustics: bool
    trace_dir: str
    vad_end_threshold: float
    use_pipecat_runtime: bool
    use_legacy_twilio_loop: bool
    use_elevenlabs_register_call: bool
    elevenlabs_api_key: str | None
    elevenlabs_agent_id: str | None
    elevenlabs_webhook_secret: str | None
    turn_min_words: int
    turn_min_chars: int
    turn_settle_ms: int
    turn_max_wait_ms: int
    barge_in_min_ms: int


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
        gradium_stt_language_hint=_env_first("GRADIUM_STT_LANGUAGE_HINT", default="en,de"),
        gradium_stt_delay_in_frames=_env_int("GRADIUM_STT_DELAY_IN_FRAMES", default=8),
        gradium_tts_padding_bonus=_env_float("GRADIUM_TTS_PADDING_BONUS", default=-0.8),
        aicoustics_api_key=_env_first("AICOUSTICS_API_KEY", "AIC_SDK_LICENSE"),
        enable_aicoustics=_env_bool("ENABLE_AICOUSTICS", default=True),
        trace_dir=_env_first("TRACE_DIR", default="traces"),
        vad_end_threshold=float(_env_first("GRADIUM_VAD_END_THRESHOLD", default="0.55")),
        use_pipecat_runtime=_env_bool("USE_PIPECAT_RUNTIME", default=True),
        use_legacy_twilio_loop=_env_bool("USE_LEGACY_TWILIO_LOOP", default=False),
        use_elevenlabs_register_call=_env_bool("USE_ELEVENLABS_REGISTER_CALL", default=False),
        elevenlabs_api_key=_env_first("ELEVENLABS_API_KEY"),
        elevenlabs_agent_id=_env_first("ELEVENLABS_AGENT_ID"),
        elevenlabs_webhook_secret=_env_first("ELEVENLABS_WEBHOOK_SECRET"),
        turn_min_words=_env_int("TURN_MIN_WORDS", default=2) or 2,
        turn_min_chars=_env_int("TURN_MIN_CHARS", default=8) or 8,
        turn_settle_ms=_env_int("TURN_SETTLE_MS", default=700) or 700,
        turn_max_wait_ms=_env_int("TURN_MAX_WAIT_MS", default=1800) or 1800,
        barge_in_min_ms=_env_int("BARGE_IN_MIN_MS", default=450) or 450,
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


def _env_int(name: str, *, default: int | None = None) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value.strip())


def _env_float(name: str, *, default: float | None = None) -> float | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return float(value.strip())
