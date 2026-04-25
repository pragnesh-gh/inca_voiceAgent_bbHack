import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from inca_voice.config import Settings
from inca_voice.elevenlabs_runtime import build_claim_from_post_call_webhook
from inca_voice.twilio_app import app


class ElevenLabsRuntimeTests(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_twilio_voice_uses_elevenlabs_register_call_when_enabled(self):
        os.environ["USE_ELEVENLABS_REGISTER_CALL"] = "1"
        os.environ["ELEVENLABS_API_KEY"] = "test-key"
        os.environ["ELEVENLABS_AGENT_ID"] = "agent-123"

        with patch("inca_voice.twilio_app.register_elevenlabs_call", return_value="<Response><Say>ok</Say></Response>") as register:
            response = TestClient(app).post(
                "/twilio/voice",
                data={"CallSid": "CA123", "From": "+4915510823559", "To": "+493075679047"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "<Response><Say>ok</Say></Response>")
        register.assert_called_once()
        kwargs = register.call_args.kwargs
        self.assertEqual(kwargs["from_number"], "+4915510823559")
        self.assertEqual(kwargs["to_number"], "+493075679047")
        self.assertEqual(kwargs["call_sid"], "CA123")

    def test_twilio_voice_falls_back_to_media_stream_when_elevenlabs_disabled(self):
        os.environ["USE_ELEVENLABS_REGISTER_CALL"] = "0"

        response = TestClient(app).post(
            "/twilio/voice",
            data={"CallSid": "CA123", "From": "+4915510823559", "To": "+493075679047"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("<Connect><Stream", response.text)

    def test_post_call_webhook_builds_claim_artifacts(self):
        import asyncio

        trace_dir = os.path.join(os.getcwd(), "traces")
        os.makedirs(trace_dir, exist_ok=True)
        settings = Settings(
            twilio_phone_number="+493075679047",
            public_base_url=None,
            google_api_key=None,
            gemini_primary_model="gemini-3-flash-preview",
            gemini_fallback_model="gemini-2.5-flash",
            gradium_api_key=None,
            gradium_asr_url="wss://example.invalid/asr",
            gradium_tts_url="wss://example.invalid/tts",
            gradium_stt_model="default",
            gradium_tts_model="default",
            gradium_voice_id="voice",
            gradium_stt_language_hint="en,de",
            gradium_stt_delay_in_frames=8,
            gradium_tts_padding_bonus=-0.8,
            aicoustics_api_key=None,
            enable_aicoustics=False,
            trace_dir=trace_dir,
            vad_end_threshold=0.55,
            use_pipecat_runtime=True,
            use_legacy_twilio_loop=False,
            use_elevenlabs_register_call=True,
            elevenlabs_api_key=None,
            elevenlabs_agent_id=None,
            elevenlabs_webhook_secret=None,
            turn_min_words=2,
            turn_min_chars=8,
            turn_settle_ms=700,
            turn_max_wait_ms=1800,
            barge_in_min_ms=450,
        )
        payload = {
            "type": "post_call_transcription",
            "data": {
                "conversation_id": "conv-123",
                "transcript": [
                    {"role": "agent", "message": "Claims desk, Stefanie speaking."},
                    {"role": "user", "message": "I had an accident and my family is hurt."},
                ],
            },
        }

        result = asyncio.run(build_claim_from_post_call_webhook(payload, settings))

        self.assertEqual(result["conversation_id"], "conv-123")
        self.assertTrue(result["trace_dir"])
        self.assertIn("Safety", result["claim_state"])
        self.assertIn("hurt", result["claim_note"])


if __name__ == "__main__":
    unittest.main()
