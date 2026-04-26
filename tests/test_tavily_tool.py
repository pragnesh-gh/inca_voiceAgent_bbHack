import json
import unittest

from fastapi.testclient import TestClient

from inca_voice.config import Settings
from inca_voice.tavily_tool import is_allowed_claim_context_query, search_claim_context
from inca_voice.twilio_app import app


def settings(api_key=None, token=None, tavily_search_url="https://api.tavily.com/search"):
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
        elevenlabs_api_key=None,
        elevenlabs_agent_id=None,
        elevenlabs_webhook_secret=None,
        policyholder_db_path="data/mock_policyholders.csv",
        policy_lookup_tool_token=None,
        scribe_final_model="gemini-2.5-pro",
        scribe_fallback_model="gemini-2.5-flash",
        scribe_final_timeout_secs=60.0,
        tavily_api_key=api_key,
        tavily_tool_token=token,
        tavily_search_url=tavily_search_url,
        tavily_max_results=3,
        turn_min_words=2,
        turn_min_chars=8,
        turn_settle_ms=700,
        turn_max_wait_ms=1800,
        barge_in_min_ms=450,
    )


class TavilyToolTests(unittest.TestCase):
    def test_allows_only_claim_context_queries(self):
        self.assertTrue(is_allowed_claim_context_query("A100 Berlin roadworks today"))
        self.assertTrue(is_allowed_claim_context_query("weather near Karl-Marx-Allee at 3pm"))
        self.assertFalse(is_allowed_claim_context_query("will this affect my SF-Klasse"))
        self.assertFalse(is_allowed_claim_context_query("does Vollkasko cover this accident"))

    def test_rejects_blocked_query_without_api_call(self):
        result = search_claim_context(settings(api_key="tvly-test"), query="Does Vollkasko cover this?")

        self.assertFalse(result["ok"])
        self.assertFalse(result["allowed"])
        self.assertEqual(result["results"], [])

    def test_formats_tavily_success_response(self):
        def fake_fetch(req, timeout):
            self.assertIn("Bearer tvly-test", req.headers["Authorization"])
            return json.dumps(
                {
                    "answer": "Light rain was reported nearby.",
                    "results": [
                        {
                            "title": "Berlin weather",
                            "url": "https://example.com/weather",
                            "content": "Light rain and reduced visibility.",
                            "score": 0.9,
                        }
                    ],
                }
            ).encode("utf-8")

        result = search_claim_context(
            settings(api_key="tvly-test"),
            query="weather near A100 Berlin",
            fetch=fake_fetch,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["allowed"])
        self.assertEqual(result["answer"], "Light rain was reported nearby.")
        self.assertEqual(result["results"][0]["title"], "Berlin weather")

    def test_rejects_non_tavily_search_url_before_fetch(self):
        def fake_fetch(_req, _timeout):
            raise AssertionError("fetch should not be called")

        result = search_claim_context(
            settings(api_key="tvly-test", tavily_search_url="http://127.0.0.1:8080/search"),
            query="weather near A100 Berlin",
            fetch=fake_fetch,
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["allowed"])
        self.assertEqual(result["uncertainty"], "search_url_not_allowed")

    def test_endpoint_requires_tool_token_when_configured(self):
        import os

        old_env = os.environ.copy()
        try:
            os.environ["TAVILY_TOOL_TOKEN"] = "secret-token"
            response = TestClient(app).post(
                "/tools/search-claim-context",
                json={"query": "weather near A100 Berlin"},
            )
            self.assertEqual(response.status_code, 401)
        finally:
            os.environ.clear()
            os.environ.update(old_env)


if __name__ == "__main__":
    unittest.main()
