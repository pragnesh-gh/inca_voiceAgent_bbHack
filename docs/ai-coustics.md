# ai-coustics

Use ai-coustics as optional real-time speech enhancement before STT, especially for noisy call environments. Source: [ai-coustics SDK quickstart](https://docs.ai-coustics.com/tutorials/sdk-quickstart), [Python SDK repo](https://github.com/ai-coustics/aic-sdk-py).

## Env Vars

```text
AIC_SDK_LICENSE=
AICOUSTICS_API_KEY=
AICOUSTICS_MODEL_ID=quail-l-8khz
AICOUSTICS_MODEL_DIR=./models
```

## Python Shape

```python
import os
import numpy as np
import aic_sdk as aic

license_key = os.environ["AIC_SDK_LICENSE"]
model_path = aic.Model.download(os.getenv("AICOUSTICS_MODEL_ID", "quail-l-8khz"), "./models")
model = aic.Model.from_file(model_path)
config = aic.ProcessorConfig.optimal(model, num_channels=1)
processor = aic.Processor(model, license_key, config)

audio = np.zeros((config.num_channels, config.num_frames), dtype=np.float32)
enhanced = processor.process(audio)
```

The quickstart shows the SDK license in `AIC_SDK_LICENSE`, model download by ID, and float32 NumPy processing buffers. It also shows `quail-vf-2.1-l-16khz` as an example model. Source: [ai-coustics SDK quickstart](https://docs.ai-coustics.com/tutorials/sdk-quickstart).

## Twilio Integration Notes

- Twilio provides mulaw/8000 mono.
- The current runtime uses an 8 kHz Quail model by default, converts PCM16 to float32, enhances it, then feeds the processed audio to STT after resampling.
- Do not send enhanced float32 directly to Twilio.
- Keep enhancement behind a flag if latency is too high during demo.

## Open Questions For Runtime Worker

- Which model gives best quality at 8 kHz phone audio with lowest latency?
- Whether enhancement should run on every frame or only before STT chunk submission.
- Whether a 1-channel config is accepted by the selected model in practice.
