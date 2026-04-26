import asyncio
import json
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from inca_voice.call_context import (
    APPROVED_SHIFT_ANCHORS,
    CallContextStore,
    build_call_dynamic_variables,
    caller_area_hint,
    enrich_call_context,
)
from inca_voice.config import Settings
from inca_voice.twilio_app import app


class CallContextTests(unittest.TestCase):
    def setUp(self):
        import os

        self._env = os.environ.copy()

    def tearDown(self):
        import os

        os.environ.clear()
        os.environ.update(self._env)

    def test_dynamic_variables_are_instant_and_safe(self):
        variables = build_call_dynamic_variables(
            from_number="+4915510823559",
            to_number="+493075679047",
            call_sid="CA123",
            now=datetime(2026, 4, 26, 9, 42, tzinfo=ZoneInfo("Europe/Berlin")),
            anchor_index=1,
        )

        self.assertEqual(variables["caller_number"], "+4915510823559")
        self.assertEqual(variables["called_number"], "+493075679047")
        self.assertEqual(variables["twilio_call_sid"], "CA123")
        self.assertEqual(variables["local_time_de"], "09:42")
        self.assertEqual(variables["weekday_de"], "Sonntag")
        self.assertEqual(variables["caller_area_hint"], "Deutschland / Mobilfunk")
        self.assertIn(variables["agent_shift_anchor"], APPROVED_SHIFT_ANCHORS)
        self.assertIn("never invent", variables["context_priming_rule"])

    def test_caller_area_hint_handles_known_and_unknown_prefixes(self):
        self.assertEqual(caller_area_hint("+493012345"), "Berlin")
        self.assertEqual(caller_area_hint("+498912345"), "Bayern / Muenchen")
        self.assertEqual(caller_area_hint("+4917212345"), "Deutschland / Mobilfunk")
        self.assertEqual(caller_area_hint("+3312345"), "Unknown caller region")

    def test_context_store_returns_still_checking_then_cached_context(self):
        store = CallContextStore(Path("tmp-test-traces") / "call-context-store")
        store.mark_pending("CA123", caller_area_hint="Berlin")

        pending = store.get_tool_response("CA123")
        self.assertTrue(pending["still_checking"])

        store.set_ready("CA123", {"caller_area_hint": "Berlin", "web_context": {"answer": "A100 traffic heavy"}})
        ready = store.get_tool_response("CA123")
        self.assertFalse(ready["still_checking"])
        self.assertEqual(ready["context"]["web_context"]["answer"], "A100 traffic heavy")

    def test_enrich_call_context_stores_result_and_handles_search_failure(self):
        store = CallContextStore(Path("tmp-test-traces") / "call-context-enrich")
        settings = fake_settings(tavily_api_key="tvly-test")

        async def fake_search(_settings, *, query, location=None, incident_time=None):
            self.assertIn("traffic", query.casefold())
            return {"ok": True, "answer": "No major road closures.", "results": []}

        asyncio.run(
            enrich_call_context(
                settings,
                store=store,
                call_sid="CA123",
                caller_number="+493012345",
                called_number="+493075679047",
                search_func=fake_search,
            )
        )
        result = store.get_tool_response("CA123")
        self.assertFalse(result["still_checking"])
        self.assertEqual(result["context"]["web_context"]["answer"], "No major road closures.")

        async def broken_search(_settings, **_kwargs):
            raise RuntimeError("network down")

        asyncio.run(
            enrich_call_context(
                settings,
                store=store,
                call_sid="CA456",
                caller_number="+493012345",
                called_number="+493075679047",
                search_func=broken_search,
            )
        )
        failed = store.get_tool_response("CA456")
        self.assertFalse(failed["still_checking"])
        self.assertIn("failed", failed["context"]["web_context"]["uncertainty"])

    def test_get_call_context_endpoint(self):
        import os

        os.environ["CALL_CONTEXT_TOOL_TOKEN"] = "ctx-secret"
        client = TestClient(app)
        denied = client.post("/tools/get-call-context", json={"twilio_call_sid": "missing"})
        allowed = client.post(
            "/tools/get-call-context",
            headers={"X-Tool-Token": "ctx-secret"},
            json={"twilio_call_sid": "missing"},
        )

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(allowed.status_code, 200)
        self.assertTrue(allowed.json()["still_checking"])


def fake_settings(tavily_api_key=None) -> Settings:
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
        trace_dir="tmp-test-traces",
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
        tavily_api_key=tavily_api_key,
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
