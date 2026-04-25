from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inca_voice.config import load_settings
from inca_voice.elevenlabs_runtime import register_elevenlabs_call


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test ElevenLabs register_call without placing a real phone call.")
    parser.add_argument("--from-number", default="+4915510823559")
    parser.add_argument("--to-number", default=None)
    args = parser.parse_args()

    load_dotenv(override=True)
    settings = load_settings()
    to_number = args.to_number or settings.twilio_phone_number
    if not to_number:
        print("Missing TWILIO_PHONE_NUMBER or --to-number", file=sys.stderr)
        return 2
    if not settings.elevenlabs_api_key or not settings.elevenlabs_agent_id:
        print("Missing ELEVENLABS_API_KEY or ELEVENLABS_AGENT_ID", file=sys.stderr)
        return 2

    try:
        twiml = register_elevenlabs_call(
            settings,
            from_number=args.from_number,
            to_number=to_number,
            call_sid="CA_LOCAL_REGISTER_CHECK",
        )
        root = ET.fromstring(twiml)
        print("ElevenLabs register_call OK")
        print(f"  Agent ID: {settings.elevenlabs_agent_id}")
        print(f"  To: {to_number}")
        print(f"  TwiML root: {root.tag}")
        print(f"  TwiML chars: {len(twiml)}")
        print(f"  TwiML preview: {twiml[:240]}")
        return 0
    except Exception as exc:
        print(f"ElevenLabs register_call check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
