from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from dotenv import load_dotenv
from livekit import api


TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"
TWILIO_TRUNKING_BASE = "https://trunking.twilio.com/v1"
LOCAL_CONFIG_PATH = Path("twilio_voice_webhook.local.json")
LIVEKIT_TRUNK_NAME = "Twilio inbound"
LIVEKIT_DISPATCH_RULE_NAME = "Twilio inbound calls"
DEFAULT_AGENT_NAME = "inca-claims-agent"


class ConfigError(RuntimeError):
    pass


def env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return None


def require_env(*names: str) -> str:
    value = env_first(*names)
    if value:
        return value
    raise ConfigError(f"Missing one of: {', '.join(names)}")


def normalize_phone_number(value: str) -> str:
    phone = re.sub(r"[\s().-]", "", value)
    if not re.fullmatch(r"\+\d{7,15}", phone):
        raise ConfigError("TWILIO_PHONE_NUMBER must be E.164, for example +491234567890")
    return phone


def infer_livekit_sip_endpoint(livekit_url: str) -> str:
    explicit = env_first("LIVEKIT_SIP_ENDPOINT", "LIVEKIT_SIP_URI")
    if explicit:
        return explicit.removeprefix("sip:").split(";")[0]

    host = parse.urlparse(livekit_url).hostname
    if host and host.endswith(".livekit.cloud"):
        return f"{host.split('.', 1)[0]}.sip.livekit.cloud"

    raise ConfigError("Set LIVEKIT_SIP_ENDPOINT for non-LiveKit Cloud URLs.")


def load_local_config() -> dict[str, str]:
    if not LOCAL_CONFIG_PATH.exists():
        return {}
    return json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))


def save_local_config(config: dict[str, str]) -> None:
    LOCAL_CONFIG_PATH.write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_webhook_config() -> dict[str, str]:
    local = load_local_config()
    livekit_url = require_env("LIVEKIT_URL")
    phone_number = normalize_phone_number(require_env("TWILIO_PHONE_NUMBER"))
    sip_endpoint = infer_livekit_sip_endpoint(livekit_url)

    auth_username = (
        env_first("LIVEKIT_SIP_AUTH_USERNAME")
        or local.get("auth_username")
        or f"inca_{secrets.token_hex(4)}"
    )
    auth_password = (
        env_first("LIVEKIT_SIP_AUTH_PASSWORD")
        or local.get("auth_password")
        or secrets.token_urlsafe(24)
    )

    return {
        "phone_number": phone_number,
        "sip_endpoint": sip_endpoint,
        "auth_username": auth_username,
        "auth_password": auth_password,
    }


class TwilioClient:
    def __init__(self) -> None:
        self.account_sid = require_env("TWILIO_ACCOUNT_SID")
        api_key = require_env("TWILIO_API_KEY", "TWILIO_API_KEY_SID", "TWILIO_API_SID")
        api_secret = require_env("TWILIO_API_SECRET", "TWILIO_API_KEY_SECRET")
        token = f"{api_key}:{api_secret}".encode("utf-8")
        self._authorization = "Basic " + base64.b64encode(token).decode("ascii")

    def request(
        self,
        method: str,
        url: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if params:
            url = f"{url}?{parse.urlencode(params)}"

        body = None
        headers = {"Authorization": self._authorization}
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
            "phone_numbers", []
        )
        for number in numbers:
            if number.get("sid") == phone_sid:
                twilio.trunking("DELETE", f"/Trunks/{trunk_sid}/PhoneNumbers/{phone_sid}")
                removed.append(trunk_sid)
    return removed


def configure_twilio_voice_url(
    twilio: TwilioClient,
    phone_sid: str,
    voice_url: str,
) -> dict[str, Any]:
    return twilio.api(
        "POST",
        f"/Accounts/{twilio.account_sid}/IncomingPhoneNumbers/{phone_sid}.json",
        data={
            "VoiceUrl": voice_url,
            "VoiceMethod": "POST",
        },
    )


async def configure_livekit(config: dict[str, str]) -> str:
    lk = api.LiveKitAPI()
    try:
        trunks = await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())
        trunk = next(
            (
                item
                for item in trunks.items
                if item.name == LIVEKIT_TRUNK_NAME
                or config["phone_number"] in item.numbers
            ),
            None,
        )
        if trunk is None:
            trunk = await lk.sip.create_inbound_trunk(
                api.CreateSIPInboundTrunkRequest(
                    trunk=api.SIPInboundTrunkInfo(
                        name=LIVEKIT_TRUNK_NAME,
                        numbers=[config["phone_number"]],
                        auth_username=config["auth_username"],
                        auth_password=config["auth_password"],
                    )
                )
            )
        else:
            update = api.SIPInboundTrunkUpdate(
                auth_username=config["auth_username"],
                auth_password=config["auth_password"],
            )
            update.numbers.set.extend([config["phone_number"]])
            update.allowed_addresses.clear = True
            trunk = await lk.sip._client.request(
                api.sip_service.SVC,
                "UpdateSIPInboundTrunk",
                api.UpdateSIPInboundTrunkRequest(
                    sip_trunk_id=trunk.sip_trunk_id,
                    update=update,
                ),
                lk.sip._admin_headers(),
                api.SIPInboundTrunkInfo,
            )

        rules = await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())
        rule = next(
            (
                item
                for item in rules.items
                if item.name == LIVEKIT_DISPATCH_RULE_NAME
                and trunk.sip_trunk_id in item.trunk_ids
            ),
            None,
        )
        agent_name = env_first("LIVEKIT_AGENT_NAME") or DEFAULT_AGENT_NAME
        if rule is None:
            rule_info = api.SIPDispatchRuleInfo(
                name=LIVEKIT_DISPATCH_RULE_NAME,
                trunk_ids=[trunk.sip_trunk_id],
                rule=api.SIPDispatchRule(
                    dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                        room_prefix=env_first("LIVEKIT_SIP_ROOM_PREFIX") or "phone-",
                    )
                ),
            )
            rule_info.room_config.agents.append(
                api.RoomAgentDispatch(agent_name=agent_name)
            )
            await lk.sip.create_dispatch_rule(
                api.CreateSIPDispatchRuleRequest(dispatch_rule=rule_info)
            )

        return trunk.sip_trunk_id
    finally:
        await lk.aclose()


def print_plan(config: dict[str, str], voice_url: str | None) -> None:
    print("Plan")
    print(f"  Twilio number: {config['phone_number']}")
    print(f"  LiveKit SIP URI in TwiML: sip:{config['phone_number']}@{config['sip_endpoint']};transport=tcp")
    print(f"  LiveKit SIP auth username: {config['auth_username']}")
    print("  LiveKit SIP auth password: SET")
    if voice_url:
        print(f"  Twilio VoiceUrl: {voice_url}")
    else:
        print("  Twilio VoiceUrl: not set until --voice-url is provided")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare Twilio Programmable Voice webhook routing into LiveKit SIP."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--voice-url",
        help="Public HTTPS URL for the webhook, for example https://abc.ngrok-free.app/twilio/voice",
    )
    args = parser.parse_args()

    load_dotenv()
    try:
        config = build_webhook_config()
        print_plan(config, args.voice_url)
        if not args.apply:
            print("")
            print("Dry run only. Re-run with --apply to update LiveKit and local webhook config.")
            return 0

        save_local_config(config)
        trunk_id = asyncio.run(configure_livekit(config))
        print(f"Configured LiveKit inbound trunk for TwiML: {trunk_id}")
        print(f"Saved local webhook config: {LOCAL_CONFIG_PATH}")

        if args.voice_url:
            twilio = TwilioClient()
            phone = find_phone_number(twilio, config["phone_number"])
            removed = detach_from_elastic_trunks(twilio, phone["sid"])
            updated = configure_twilio_voice_url(twilio, phone["sid"], args.voice_url)
            print(f"Detached from Elastic SIP trunks: {removed or 'none'}")
            print(f"Updated Twilio VoiceUrl for {updated.get('phone_number')}")
        else:
            print("Twilio VoiceUrl not changed yet. Provide --voice-url after starting a tunnel.")

        return 0
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
