import asyncio
import unittest

from inca_voice.config import Settings
from inca_voice.twilio_app import TwilioMediaSession


class DummyWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


class DummyTrace:
    def __init__(self):
        self.transcripts = []
        self.events = []
        self.errors = []

    def transcript(self, speaker, text, **fields):
        self.transcripts.append((speaker, text, fields))

    def event(self, event, **fields):
        self.events.append((event, fields))

    def error(self, where, exc, **fields):
        self.errors.append((where, exc, fields))

    @property
    def elapsed_ms(self):
        return 0.0


class DummyTTS:
    async def synthesize_ulaw(self, text):
        yield b"\xff" * 160


class SlowScribe:
    def __init__(self):
        self.state = {}
        self.turns = []

    async def record_turn(self, speaker, text):
        self.turns.append((speaker, text))
        await asyncio.sleep(10)

    async def close(self):
        return None


class FastResponder:
    async def reply(self, user_text, claim_state):
        return "Are you somewhere safe right now?"


def settings():
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
        use_elevenlabs_register_call=False,
        elevenlabs_api_key=None,
        elevenlabs_agent_id=None,
        elevenlabs_webhook_secret=None,
        turn_min_words=2,
        turn_min_chars=8,
        turn_settle_ms=700,
        turn_max_wait_ms=1800,
        barge_in_min_ms=450,
    )


class TwilioMediaSessionTests(unittest.TestCase):
    def test_closed_session_does_not_send_tts(self):
        session = TwilioMediaSession(DummyWebSocket(), settings())
        session.stream_sid = "MZ123"
        session.trace = DummyTrace()
        session.tts = DummyTTS()
        session.closed = True

        asyncio.run(session.say("This should not be sent"))

        self.assertEqual(session.websocket.sent, [])
        self.assertEqual(session.trace.transcripts, [])

    def test_commit_turn_starts_response_without_waiting_for_slow_scribe(self):
        async def run():
            session = TwilioMediaSession(DummyWebSocket(), settings())
            session.stream_sid = "MZ123"
            session.trace = DummyTrace()
            session.tts = DummyTTS()
            session.scribe = SlowScribe()
            session.responder = FastResponder()

            await session._commit_turn(type("Turn", (), {"text": "I had an accident.", "metadata": {}})())
            await asyncio.sleep(0.05)

            self.assertTrue(session.websocket.sent)
            await session._close("test_done")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
