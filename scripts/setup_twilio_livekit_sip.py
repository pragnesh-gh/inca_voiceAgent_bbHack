from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from dotenv import load_dotenv
from livekit import api


TWILIO_TRUNKING_BASE = "https://trunking.twilio.com/v1"
TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"


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
        raise ConfigError(
            "TWILIO_PHONE_NUMBER must be E.164, for example +491234567890"
        )
    return phone


def slug(value: str, max_len: int = 52) -> str:
    lowered = value.lower()
    cleaned = re.sub(r"[^a-z0-9-]+", "-", lowered)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned[:max_len].strip("-") or "livekit"


def infer_livekit_sip_endpoint(livekit_url: str) -> str:
    explicit_uri = env_first("LIVEKIT_SIP_URI")
    if explicit_uri:
        endpoint = explicit_uri.removeprefix("sip:")
        endpoint = endpoint.split(";")[0]
        return endpoint

    explicit_endpoint = env_first("LIVEKIT_SIP_ENDPOINT")
    if explicit_endpoint:
        return explicit_endpoint.removeprefix("sip:").split(";")[0]

    host = parse.urlparse(livekit_url).hostname
    if host and host.endswith(".livekit.cloud"):
        project = host.split(".", 1)[0]
        return f"{project}.sip.livekit.cloud"

    raise ConfigError(
        "Could not infer LiveKit SIP endpoint. Set LIVEKIT_SIP_URI, for example "
        "sip:<project>.sip.livekit.cloud"
    )


@dataclass(frozen=True)
class SetupConfig:
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    livekit_sip_endpoint: str
    phone_number: str
    twilio_account_sid: str
    twilio_api_key_sid: str
    twilio_api_key_secret: str
    twilio_phone_number_sid: str | None
    twilio_trunk_sid: str | None
    twilio_trunk_name: str
    twilio_trunk_domain_name: str
    livekit_trunk_name: str
    livekit_dispatch_rule_name: str
    livekit_room_prefix: str
    livekit_agent_name: str | None

    @property
    def livekit_sip_uri_for_twilio(self) -> str:
        return f"sip:{self.livekit_sip_endpoint};transport=tcp"


def load_config() -> SetupConfig:
    load_dotenv()

    missing: list[str] = []

    def needed(*names: str) -> str:
        value = env_first(*names)
        if value:
            return value
        missing.append(" / ".join(names))
        return ""

    livekit_url = needed("LIVEKIT_URL")
    livekit_api_key = needed("LIVEKIT_API_KEY")
    livekit_api_secret = needed("LIVEKIT_API_SECRET")
    twilio_account_sid = needed("TWILIO_ACCOUNT_SID")
    twilio_api_key_sid = needed(
        "TWILIO_API_KEY_SID",
        "TWILIO_API_SID",
        "TWILIO_API_KEY",
    )
    twilio_api_key_secret = needed(
        "TWILIO_API_KEY_SECRET",
        "TWILIO_API_SECRET",
    )
    twilio_phone_number = needed("TWILIO_PHONE_NUMBER")

    if missing:
        raise ConfigError("Missing required env vars: " + "; ".join(missing))

    endpoint = infer_livekit_sip_endpoint(livekit_url)
    project_slug = slug(endpoint.split(".", 1)[0])
    phone = normalize_phone_number(twilio_phone_number)

    trunk_name = env_first("TWILIO_TRUNK_NAME") or "Inca LiveKit SIP"
    domain_name = (
        env_first("TWILIO_TRUNK_DOMAIN_NAME")
        or f"{project_slug}-twilio.pstn.twilio.com"
    )
    if not domain_name.endswith(".pstn.twilio.com"):
        raise ConfigError("TWILIO_TRUNK_DOMAIN_NAME must end with .pstn.twilio.com")

    return SetupConfig(
        livekit_url=livekit_url,
        livekit_api_key=livekit_api_key,
        livekit_api_secret=livekit_api_secret,
        livekit_sip_endpoint=endpoint,
        phone_number=phone,
        twilio_account_sid=twilio_account_sid,
        twilio_api_key_sid=twilio_api_key_sid,
        twilio_api_key_secret=twilio_api_key_secret,
        twilio_phone_number_sid=env_first("TWILIO_PHONE_NUMBER_SID"),
        twilio_trunk_sid=env_first("TWILIO_TRUNK_SID"),
        twilio_trunk_name=trunk_name,
        twilio_trunk_domain_name=domain_name,
        livekit_trunk_name=env_first("LIVEKIT_SIP_INBOUND_TRUNK_NAME")
        or "Twilio inbound",
        livekit_dispatch_rule_name=env_first("LIVEKIT_SIP_DISPATCH_RULE_NAME")
        or "Twilio inbound calls",
        livekit_room_prefix=env_first("LIVEKIT_SIP_ROOM_PREFIX") or "phone-",
        livekit_agent_name=env_first("LIVEKIT_AGENT_NAME") or "inca-claims-agent",
    )


class TwilioClient:
    def __init__(self, api_key_sid: str, api_key_secret: str):
        token = f"{api_key_sid}:{api_key_secret}".encode("utf-8")
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

    def trunking(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.request(method, f"{TWILIO_TRUNKING_BASE}{path}", **kwargs)

    def account_api(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.request(method, f"{TWILIO_API_BASE}{path}", **kwargs)


def print_plan(config: SetupConfig) -> None:
    print("Plan")
    print(f"  LiveKit URL: {config.livekit_url}")
    print(f"  LiveKit SIP URI for Twilio: {config.livekit_sip_uri_for_twilio}")
    print(f"  Twilio phone number: {config.phone_number}")
    print(f"  Twilio trunk name: {config.twilio_trunk_name}")
    print(f"  Twilio trunk domain: {config.twilio_trunk_domain_name}")
    print(f"  LiveKit inbound trunk: {config.livekit_trunk_name}")
    print(f"  LiveKit dispatch rule: {config.livekit_dispatch_rule_name}")
    print(f"  LiveKit room prefix: {config.livekit_room_prefix}")
    if config.livekit_agent_name:
        print(f"  Dispatch named agent: {config.livekit_agent_name}")
    else:
        print("  Dispatch named agent: no, using default unnamed agent auto-dispatch")


async def ensure_livekit(config: SetupConfig) -> tuple[str, str]:
    lkapi = api.LiveKitAPI(
        url=config.livekit_url,
        api_key=config.livekit_api_key,
        api_secret=config.livekit_api_secret,
    )
    try:
        inbound = await lkapi.sip.list_inbound_trunk(
            api.ListSIPInboundTrunkRequest()
        )
        trunk = next(
            (
                item
                for item in inbound.items
                if config.phone_number in item.numbers
                or item.name == config.livekit_trunk_name
            ),
            None,
        )
        if trunk is None:
            trunk = await lkapi.sip.create_inbound_trunk(
                api.CreateSIPInboundTrunkRequest(
                    trunk=api.SIPInboundTrunkInfo(
                        name=config.livekit_trunk_name,
                        numbers=[config.phone_number],
                    )
                )
            )
            print(f"Created LiveKit inbound trunk: {trunk.sip_trunk_id}")
        else:
            print(f"Reusing LiveKit inbound trunk: {trunk.sip_trunk_id}")

        dispatch_rules = await lkapi.sip.list_dispatch_rule(
            api.ListSIPDispatchRuleRequest()
        )
        dispatch = next(
            (
                item
                for item in dispatch_rules.items
                if item.name == config.livekit_dispatch_rule_name
                and trunk.sip_trunk_id in item.trunk_ids
            ),
            None,
        )
        if dispatch is None:
            rule_info = api.SIPDispatchRuleInfo(
                name=config.livekit_dispatch_rule_name,
                trunk_ids=[trunk.sip_trunk_id],
                rule=api.SIPDispatchRule(
                    dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                        room_prefix=config.livekit_room_prefix,
                    )
                ),
            )
            if config.livekit_agent_name:
                rule_info.room_config.agents.append(
                    api.RoomAgentDispatch(agent_name=config.livekit_agent_name)
                )

            dispatch = await lkapi.sip.create_dispatch_rule(
                api.CreateSIPDispatchRuleRequest(dispatch_rule=rule_info)
            )
            print(f"Created LiveKit dispatch rule: {dispatch.sip_dispatch_rule_id}")
        else:
            current_agents = [
                agent.agent_name for agent in dispatch.room_config.agents
            ]
            if config.livekit_agent_name not in current_agents:
                dispatch.room_config.agents.append(
                    api.RoomAgentDispatch(agent_name=config.livekit_agent_name)
                )
                dispatch = await lkapi.sip.update_dispatch_rule(
                    dispatch.sip_dispatch_rule_id,
                    dispatch,
                )
                print(
                    "Updated LiveKit dispatch rule with agent: "
                    f"{dispatch.sip_dispatch_rule_id}"
                )
            else:
                print(
                    f"Reusing LiveKit dispatch rule: {dispatch.sip_dispatch_rule_id}"
                )

        return trunk.sip_trunk_id, dispatch.sip_dispatch_rule_id
    finally:
        await lkapi.aclose()


def find_or_create_twilio_trunk(client: TwilioClient, config: SetupConfig) -> str:
    if config.twilio_trunk_sid:
        print(f"Using Twilio trunk from TWILIO_TRUNK_SID: {config.twilio_trunk_sid}")
        return config.twilio_trunk_sid

    trunks = client.trunking("GET", "/Trunks").get("trunks", [])
    for trunk in trunks:
        if (
            trunk.get("domain_name") == config.twilio_trunk_domain_name
            or trunk.get("friendly_name") == config.twilio_trunk_name
        ):
            print(f"Reusing Twilio trunk: {trunk['sid']}")
            return trunk["sid"]

    trunk = client.trunking(
        "POST",
        "/Trunks",
        data={
            "FriendlyName": config.twilio_trunk_name,
            "DomainName": config.twilio_trunk_domain_name,
        },
    )
    print(f"Created Twilio trunk: {trunk['sid']}")
    return trunk["sid"]


def ensure_twilio_origination(
    client: TwilioClient, config: SetupConfig, trunk_sid: str
) -> None:
    urls = client.trunking("GET", f"/Trunks/{trunk_sid}/OriginationUrls").get(
        "origination_urls", []
    )
    for item in urls:
        if item.get("sip_url") == config.livekit_sip_uri_for_twilio:
            print(f"Reusing Twilio origination URL: {item['sid']}")
            return

    created = client.trunking(
        "POST",
        f"/Trunks/{trunk_sid}/OriginationUrls",
        data={
            "FriendlyName": "LiveKit SIP URI",
            "SipUrl": config.livekit_sip_uri_for_twilio,
            "Weight": "1",
            "Priority": "1",
            "Enabled": "true",
        },
    )
    print(f"Created Twilio origination URL: {created['sid']}")


def find_twilio_phone_number_sid(client: TwilioClient, config: SetupConfig) -> str:
    if config.twilio_phone_number_sid:
        return config.twilio_phone_number_sid

    response = client.account_api(
        "GET",
        f"/Accounts/{config.twilio_account_sid}/IncomingPhoneNumbers.json",
        params={"PhoneNumber": config.phone_number},
    )
    numbers = response.get("incoming_phone_numbers", [])
    if not numbers:
        raise RuntimeError(
            f"Could not find Twilio IncomingPhoneNumber for {config.phone_number}"
        )
    return numbers[0]["sid"]


def ensure_twilio_phone_number(
    client: TwilioClient, config: SetupConfig, trunk_sid: str
) -> None:
    phone_number_sid = find_twilio_phone_number_sid(client, config)
    numbers = client.trunking("GET", f"/Trunks/{trunk_sid}/PhoneNumbers").get(
        "phone_numbers", []
    )
    for item in numbers:
        if item.get("sid") == phone_number_sid or item.get("phone_number") == config.phone_number:
            print(f"Reusing Twilio trunk phone number: {phone_number_sid}")
            return

    created = client.trunking(
        "POST",
        f"/Trunks/{trunk_sid}/PhoneNumbers",
        data={"PhoneNumberSid": phone_number_sid},
    )
    print(f"Associated Twilio phone number with trunk: {created['sid']}")


async def apply_setup(config: SetupConfig) -> None:
    await ensure_livekit(config)

    twilio = TwilioClient(config.twilio_api_key_sid, config.twilio_api_key_secret)
    trunk_sid = find_or_create_twilio_trunk(twilio, config)
    ensure_twilio_origination(twilio, config, trunk_sid)
    ensure_twilio_phone_number(twilio, config, trunk_sid)

    print("")
    print("Ready to test:")
    print("  1. Run: python agent.py dev")
    print(f"  2. Call: {config.phone_number}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set up Twilio Elastic SIP Trunking for LiveKit inbound calls."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create/reuse LiveKit SIP objects and Twilio trunk resources.",
    )
    args = parser.parse_args()

    try:
        config = load_config()
        print_plan(config)
        if not args.apply:
            print("")
            print("Dry run only. Re-run with --apply to make external changes.")
            return 0

        asyncio.run(apply_setup(config))
        return 0
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
