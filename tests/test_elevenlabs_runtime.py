import os
import unittest
from dataclasses import replace
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient

from inca_voice.config import Settings
from inca_voice.elevenlabs_runtime import build_claim_from_post_call_webhook, register_elevenlabs_call
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

        with (
            patch("inca_voice.twilio_app.register_elevenlabs_call", return_value="<Response><Say>ok</Say></Response>") as register,
            patch("inca_voice.twilio_app.start_call_context_enrichment") as start_context,
        ):
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
        start_context.assert_called_once()

    def test_twilio_voice_returns_even_if_context_enrichment_schedule_fails(self):
        os.environ["USE_ELEVENLABS_REGISTER_CALL"] = "1"
        os.environ["ELEVENLABS_API_KEY"] = "test-key"
        os.environ["ELEVENLABS_AGENT_ID"] = "agent-123"

        with (
            patch("inca_voice.twilio_app.register_elevenlabs_call", return_value="<Response><Say>ok</Say></Response>"),
            patch("inca_voice.twilio_app.start_call_context_enrichment", side_effect=RuntimeError("scheduler failed")),
        ):
            response = TestClient(app).post(
                "/twilio/voice",
                data={"CallSid": "CA123", "From": "+4915510823559", "To": "+493075679047"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "<Response><Say>ok</Say></Response>")

    def test_register_call_passes_context_dynamic_variables(self):
        settings = minimal_settings()
        captured = {}

        class FakeTwilio:
            def register_call(self, **kwargs):
                captured.update(kwargs)
                return "<Response />"

        class FakeConversationalAI:
            def __init__(self):
                self.twilio = FakeTwilio()

        class FakeClient:
            def __init__(self, api_key):
                self.conversational_ai = FakeConversationalAI()

        with patch("inca_voice.elevenlabs_runtime.ElevenLabs", FakeClient):
            twiml = register_elevenlabs_call(
                settings,
                from_number="+4915510823559",
                to_number="+493075679047",
                call_sid="CA123",
            )

        self.assertEqual(twiml, "<Response />")
        variables = captured["conversation_initiation_client_data"]["dynamic_variables"]
        self.assertEqual(variables["caller_number"], "+4915510823559")
        self.assertEqual(variables["twilio_call_sid"], "CA123")
        self.assertIn("local_time_de", variables)
        self.assertIn("weekday_de", variables)
        self.assertEqual(variables["caller_area_hint"], "Deutschland / Mobilfunk")
        self.assertIn("agent_shift_anchor", variables)
        self.assertIn("context_priming_rule", variables)

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

        trace_dir = os.path.join(os.getcwd(), "tmp-test-traces", uuid4().hex)
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
            policyholder_db_path="data/mock_policyholders.csv",
            policy_lookup_tool_token=None,
            scribe_final_model="gemini-2.5-pro",
            scribe_fallback_model="gemini-2.5-flash",
            scribe_final_timeout_secs=60.0,
            tavily_api_key=None,
            tavily_tool_token=None,
            tavily_search_url="https://api.tavily.com/search",
            tavily_max_results=3,
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
                    {"role": "user", "message": "My name is Pragnesh and I'm born, um, October 26th, 2001."},
                    {"role": "user", "message": "I had an accident and my family is hurt."},
                ],
            },
        }

        result = asyncio.run(build_claim_from_post_call_webhook(payload, settings))

        self.assertEqual(result["conversation_id"], "conv-123")
        self.assertTrue(result["trace_dir"])
        self.assertIn("Safety", result["claim_state"])
        self.assertIn("FNOL Auto Loss Notice", result["claim_note"])
        self.assertIn("2001-10-26", result["claim_note"])
        self.assertIn("MM-KFZ-4831", result["claim_note"])
        self.assertIn("hurt", result["claim_note"])
        self.assertIn("quality", result)
        self.assertIn("FNOL Validation Checklist", result["claim_note"])
        self.assertIn("Missing: Whether caller/vehicle is somewhere safe", result["claim_note"])
        self.assertIn("elevenlabs-postcall_conv-123", result["trace_dir"])
        self.assertTrue(os.path.exists(os.path.join(trace_dir, "LATEST_CLAIM_NOTE.md")))
        self.assertTrue(os.path.exists(os.path.join(trace_dir, "LATEST_FNOL_AUTO_LOSS_NOTICE.md")))
        self.assertTrue(os.path.exists(os.path.join(trace_dir, "LATEST_FNOL_AUTO_LOSS_NOTICE_REDACTED.md")))
        self.assertTrue(os.path.exists(os.path.join(trace_dir, "LATEST_FNOL_AUTO_LOSS_NOTICE_REDACTED.pdf")))
        self.assertTrue(os.path.exists(os.path.join(trace_dir, "LATEST_CLAIM_STATE.json")))
        self.assertTrue(os.path.exists(os.path.join(trace_dir, "LATEST_TRACE_DIR.txt")))
        with open(os.path.join(trace_dir, "LATEST_FNOL_AUTO_LOSS_NOTICE_REDACTED.md"), encoding="utf-8") as handle:
            redacted = handle.read()
        self.assertNotIn("MM-KFZ-4831", redacted)
        self.assertNotIn("2001-10-26", redacted)
        self.assertIn("[POLICY]", redacted)
        with open(os.path.join(trace_dir, "LATEST_TRACE_DIR.txt"), encoding="utf-8") as handle:
            self.assertEqual(os.path.abspath(result["trace_dir"]), handle.read().strip())

    def test_post_call_scribe_extracts_core_facts_from_natural_claim_story(self):
        import asyncio

        trace_dir = os.path.join(os.getcwd(), "tmp-test-traces", uuid4().hex)
        os.makedirs(trace_dir, exist_ok=True)
        settings = replace(minimal_settings(), trace_dir=trace_dir, google_api_key=None)
        payload = {
            "type": "post_call_transcription",
            "data": {
                "conversation_id": "conv-natural-claim",
                "transcript": [
                    {"role": "agent", "message": "Meridian Mutual claims, Stefanie speaking. How can I help today?", "time_in_call_secs": 1},
                    {"role": "user", "message": "Um, I am here to, um, have, uh, an accident incident to claim.", "time_in_call_secs": 6},
                    {"role": "agent", "message": "Okay, let me help you get this started. Can I get your policy number, or your name and date of birth?", "time_in_call_secs": 16},
                    {"role": "user", "message": "My name is Mark Schneider. Uh, date of birth is 14th March, 1978.", "time_in_call_secs": 23},
                    {"role": "user", "message": "Um, it happened today around 8:20 in the morning, uh, near Innsbruck Platz in Berlin. And it was raining, road was wet, and, um, a white Mercedes hit me from behind, and the traffic slowed down.", "time_in_call_secs": 45},
                    {"role": "user", "message": "No, I'm safe. I'm back home. Uh, no one was hurt. The rear bumper and the parking sensors were damaged, though. But, uh, it makes a warning sound.", "time_in_call_secs": 77},
                    {"role": "user", "message": "His name was Nico Hoffman, and I think his plate was, uh, BDL7342.", "time_in_call_secs": 106},
                    {"role": "user", "message": "Um, police were not called because we exchanged details, but I did take photos.", "time_in_call_secs": 131},
                    {"role": "user", "message": "It's drivable. Damaged on the back, but drivable. Um, yeah, it's with me. I mean, I have... It's at the garage for now. Not with me at home.", "time_in_call_secs": 149},
                ],
            },
        }

        result = asyncio.run(build_claim_from_post_call_webhook(payload, settings))
        state = result["claim_state"]

        self.assertIs(state["Safety"]["fields"]["safe_location"]["value"], True)
        self.assertIs(state["Safety"]["fields"]["injuries_reported"]["value"], False)
        self.assertEqual(state["Loss"]["fields"]["date"]["value"], "today")
        self.assertEqual(state["Loss"]["fields"]["time"]["value"], "08:20")
        self.assertEqual(state["Loss"]["fields"]["location"]["value"], "Innsbruck Platz in Berlin")
        self.assertIn("white mercedes", state["Loss"]["fields"]["summary"]["value"].lower())
        self.assertIs(state["Loss"]["fields"]["drivable"]["value"], True)
        self.assertIn("rear bumper", state["Vehicles"]["fields"]["damage_description"]["value"].lower())
        self.assertIn("parking sensors", state["Vehicles"]["fields"]["damage_description"]["value"].lower())
        self.assertIn("garage", state["Vehicles"]["fields"]["current_vehicle_location"]["value"].lower())
        self.assertIs(state["People"]["fields"]["other_party_involved"]["value"], True)
        self.assertIs(state["Police"]["fields"]["called"]["value"], False)
        self.assertIs(state["Evidence"]["fields"]["photos_available"]["value"], True)
        self.assertNotIn("Missing: Date of loss", result["claim_note"])
        self.assertNotIn("Missing: Time of loss", result["claim_note"])
        self.assertNotIn("Missing: Whether the vehicle is drivable", result["claim_note"])
        self.assertNotIn("Missing: Vehicle damage description", result["claim_note"])
        self.assertNotIn("Missing: Current vehicle location", result["claim_note"])
        self.assertNotIn("Missing: Whether another party was involved", result["claim_note"])
        self.assertNotIn("Missing: Whether police were involved", result["claim_note"])
        self.assertIn("white Mercedes", result["claim_note"])

def minimal_settings() -> Settings:
    return Settings(
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
        trace_dir="traces",
        vad_end_threshold=0.55,
        use_pipecat_runtime=True,
        use_legacy_twilio_loop=False,
        use_elevenlabs_register_call=True,
        elevenlabs_api_key="test-key",
        elevenlabs_agent_id="agent-123",
        elevenlabs_webhook_secret=None,
        policyholder_db_path="data/mock_policyholders.csv",
        policy_lookup_tool_token=None,
        scribe_final_model="gemini-2.5-pro",
        scribe_fallback_model="gemini-2.5-flash",
        scribe_final_timeout_secs=60.0,
        tavily_api_key=None,
        tavily_tool_token=None,
        tavily_search_url="https://api.tavily.com/search",
        tavily_max_results=3,
        turn_min_words=2,
        turn_min_chars=8,
        turn_settle_ms=700,
        turn_max_wait_ms=1800,
        barge_in_min_ms=450,
    )


if __name__ == "__main__":
    unittest.main()
