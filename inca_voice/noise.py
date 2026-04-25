from __future__ import annotations

import os
from typing import Any

from .config import Settings


class NoiseEnhancer:
    """Best-effort ai-coustics wrapper.

    The direct phone loop must work even if the SDK is unavailable or its model
    contract changes, so enhancement is optional and trace-visible.
    """

    def __init__(self, settings: Settings, trace: Any) -> None:
        self.enabled = False
        self.trace = trace
        self._enhancer: Any = None
        if not settings.enable_aicoustics or not settings.aicoustics_api_key:
            trace.event("aicoustics_disabled")
            return

        os.environ.setdefault("AIC_SDK_LICENSE", settings.aicoustics_api_key)
        try:
            import aic_sdk as aic  # type: ignore

            model_id = os.getenv("AICOUSTICS_MODEL_ID", "quail-l-8khz")
            model_dir = os.getenv("AICOUSTICS_MODEL_DIR", "models")
            model_path = aic.Model.download(model_id, model_dir)
            model = aic.Model.from_file(model_path)
            config = aic.ProcessorConfig(
                sample_rate=8000,
                num_channels=1,
                num_frames=160,
                allow_variable_frames=True,
            )
            self._enhancer = aic.Processor(model, settings.aicoustics_api_key, config)
            self._aic = aic
            self.enabled = True
            trace.event("aicoustics_enabled", model_id=model_id)
        except Exception as exc:  # pragma: no cover - depends on vendor package.
            trace.error("aicoustics_init", exc)
            trace.event("aicoustics_bypassed")

    def enhance_pcm16_8k(self, pcm: bytes) -> bytes:
        if not self.enabled or self._enhancer is None:
            return pcm
        try:
            import numpy as np

            samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
            audio = samples.reshape(1, -1)
            processed = self._enhancer.process(audio)
            clipped = np.clip(processed.reshape(-1), -1.0, 1.0)
            return (clipped * 32767.0).astype("<i2").tobytes()
        except Exception as exc:  # pragma: no cover - depends on vendor package.
            self.trace.error("aicoustics_enhance", exc)
            self.enabled = False
            return pcm
