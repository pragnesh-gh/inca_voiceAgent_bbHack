import asyncio
import unittest

from inca_voice.pipecat_bridge import PipecatTwilioMediaCodec, pipecat_available


class PipecatBridgeTests(unittest.TestCase):
    def test_pipecat_package_is_available(self):
        self.assertTrue(pipecat_available())

    def test_codec_encodes_pcm16_to_twilio_media_payload(self):
        async def run():
            codec = PipecatTwilioMediaCodec(stream_sid="MZ123", call_sid="CA123")
            await codec.setup()
            message = await codec.encode_pcm16_8k(b"\x00\x00" * 160)
            self.assertEqual(message["event"], "media")
            self.assertEqual(message["streamSid"], "MZ123")
            self.assertTrue(message["media"]["payload"])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
