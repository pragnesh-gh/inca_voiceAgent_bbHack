from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from typing import Any
from urllib import error, parse, request

from dotenv import load_dotenv


TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"
TWILIO_TRUNKING_BASE = "https://trunking.twilio.com/v1"


class ConfigError(RuntimeError):
    pass


class TwilioClient:
    def __init__(self) -> None:
        self.account_sid = require_env("TWILIO_ACCOUNT_SID")
        api_key = require_env("TWILIO_API_KEY", "TWILIO_API_KEY_SID", "TWILIO_API_SID")
        api_secret = require_env("TWILIO_API_SECRET", "TWILIO_API_KEY_SECRET")
        token = f"{api_key}:{api_secret}".encode("utf-8")
        self.authorization = "Basic " + base64.b64encode(token).decode("ascii")

    def request(
        self,
        method: str,
        url: str,
        *,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if params:
            url = f"{url}?{parse.urlencode(params)}"
        headers = {"Authorization": self.authorization}
        body = None
        if data is not None:
            body = parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = request.Request(url, data=body, method=method, headers=headers)
        try:
            with request.urlopen(req, timeout=20) as response:
                text = response.read().decode("utf-8")
        except error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Twilio API {exc.code}: {text}") from exc
        return json.loads(text) if text else {}

    def api(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.request(method, f"{TWILIO_API_BASE}{path}", **kwargs)

    def trunking(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.request(method, f"{TWILIO_TRUNKING_BASE}{path}", **kwargs)


def env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip().strip('"').strip("'")
    return None


def require_env(*names: str) -> str:
    value = env_first(*names)
    if value:
        return value
    raise ConfigError(f"Missing one of: {', '.join(names)}")


def normalize_phone(value: str) -> str:
    phone = re.sub(r"[\s().-]", "", value)
    if not re.fullmatch(r"\+\d{7,15}", phone):
        raise ConfigError("TWILIO_PHONE_NUMBER must be E.164, for example +493075679047")
    return phone


def normalize_voice_url(public_url: str) -> str:
    parsed = parse.urlparse(public_url.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError("Public URL must be an absolute https URL.")
    path = parsed.path.rstrip("/")
    if path in {"", "/"}:
        path = "/twilio/voice"
    return parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def find_phone_number(twilio: TwilioClient, phone_number: str) -> dict[str, Any]:
    response = twilio.api(
        "GET",
        f"/Accounts/{twilio.account_sid}/IncomingPhoneNumbers.json",
        params={"PhoneNumber": phone_number},
    )
    numbers = response.get("incoming_phone_numbers", [])
    if not numbers:
        raise RuntimeError(f"Could not find Twilio number {phone_number}")
    return numbers[0]


def detach_from_elastic_trunks(twilio: TwilioClient, phone_sid: str) -> list[str]:
    removed: list[str] = []
    trunks = twilio.trunking("GET", "/Trunks").get("trunks", [])
    for trunk in trunks:
        trunk_sid = trunk["sid"]
        numbers = twilio.trunking("GET", f"/Trunks/{trunk_sid}/PhoneNumbers").get(
            "phone_numbers",
            [],
        )
        for number in numbers:
            if number.get("sid") == phone_sid:
                twilio.trunking("DELETE", f"/Trunks/{trunk_sid}/PhoneNumbers/{phone_sid}")
                removed.append(trunk_sid)
    return removed


def configure_voice_url(twilio: TwilioClient, phone_sid: str, voice_url: str) -> dict[str, Any]:
    return twilio.api(
        "POST",
        f"/Accounts/{twilio.account_sid}/IncomingPhoneNumbers/{phone_sid}.json",
        data={"VoiceUrl": voice_url, "VoiceMethod": "POST"},
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Point a Twilio phone number at the Inca voice webhook."
    )
    parser.add_argument("--public-url", required=True, help="Tunnel/app URL, e.g. https://name.ngrok.app")
    parser.add_argument("--apply", action="store_true", help="Actually update Twilio")
    parser.add_argument(
        "--keep-trunks",
        action="store_true",
        help="Do not detach this number from Elastic SIP trunks first.",
    )
    args = parser.parse_args()

    load_dotenv(override=True)
    try:
        phone_number = normalize_phone(require_env("TWILIO_PHONE_NUMBER"))
        voice_url = normalize_voice_url(args.public_url)
        print("Plan")
        print(f"  Twilio number: {phone_number}")
        print(f"  VoiceUrl: {voice_url}")
        runtime = "ElevenLabs Register Call" if env_first("USE_ELEVENLABS_REGISTER_CALL") else "direct Twilio Media Streams fallback"
        print(f"  Runtime: {runtime}, no SIP trunk")
        if not args.apply:
            print("Dry run only. Add --apply to update Twilio.")
            return 0

        twilio = TwilioClient()
        phone = find_phone_number(twilio, phone_number)
        removed = [] if args.keep_trunks else detach_from_elastic_trunks(twilio, phone["sid"])
        updated = configure_voice_url(twilio, phone["sid"], voice_url)
        print(f"Detached from Elastic SIP trunks: {removed or 'none'}")
        print(f"Updated Twilio VoiceUrl for {updated.get('phone_number')}")
        return 0
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
