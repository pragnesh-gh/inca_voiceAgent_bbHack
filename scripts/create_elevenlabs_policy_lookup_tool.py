from __future__ import annotations

import argparse
import json
import os
import sys
from urllib import error, request

from dotenv import load_dotenv


API_BASE = "https://api.elevenlabs.io/v1/convai"


class ConfigError(RuntimeError):
    pass


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


def normalize_public_url(value: str) -> str:
    base = value.rstrip("/")
    if not base.startswith("https://"):
        raise ConfigError("PUBLIC_BASE_URL must be an https URL for ElevenLabs server tools")
    return f"{base}/tools/lookup-policyholder"


def build_tool_config(public_url: str, tool_token: str | None) -> dict[str, object]:
    request_headers = {}
    if tool_token:
        request_headers["X-Tool-Token"] = tool_token
    return {
        "tool_config": {
            "type": "webhook",
            "name": "lookup_policyholder",
            "description": (
                "Looks up a policyholder in the Meridian Mutual demo policy database by name, "
                "date of birth, phone number, policy number, or license plate. Use during "
                "identity/orientation, not during emergency safety triage."
            ),
            "response_timeout_secs": 6,
            "disable_interruptions": False,
            "force_pre_tool_speech": True,
            "tool_call_sound_behavior": "auto",
            "api_schema": {
                "url": public_url,
                "method": "POST",
                "path_params_schema": {},
                "request_body_schema": {
                    "type": "object",
                    "description": "Policyholder lookup for claim intake identity confirmation.",
                    "properties": {
                        "name": {"type": "string", "description": "Caller or insured full name if known."},
                        "date_of_birth": {"type": "string", "description": "Date of birth in YYYY-MM-DD if known."},
                        "phone": {"type": "string", "description": "Caller phone number if known."},
                        "policy_number": {"type": "string", "description": "Policy number if known."},
                        "license_plate": {"type": "string", "description": "Vehicle license plate if known."},
                    },
                },
                "request_headers": request_headers,
            },
        }
    }


def create_tool(api_key: str, payload: dict[str, object]) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{API_BASE}/tools",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "xi-api-key": api_key},
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ElevenLabs API {exc.code}: {text}") from exc


def redact_payload(value):
    if isinstance(value, dict):
        return {
            key: "SET" if key.casefold() in {"x-tool-token", "authorization", "api-key", "xi-api-key"} else redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the ElevenLabs lookup_policyholder server tool.")
    parser.add_argument("--apply", action="store_true", help="Actually create the tool in ElevenLabs.")
    args = parser.parse_args()

    load_dotenv(override=True)
    try:
        api_key = require_env("ELEVENLABS_API_KEY")
        public_url = normalize_public_url(require_env("PUBLIC_BASE_URL", "PUBLIC_URL"))
        payload = build_tool_config(public_url, env_first("POLICY_LOOKUP_TOOL_TOKEN", "ELEVENLABS_TOOL_TOKEN"))
        print("Plan")
        print(f"  Tool name: {payload['tool_config']['name']}")
        print(f"  Webhook URL: {public_url}")
        print(f"  Tool token header: {'SET' if env_first('POLICY_LOOKUP_TOOL_TOKEN', 'ELEVENLABS_TOOL_TOKEN') else 'not set'}")
        if not args.apply:
            print("Dry run only. Add --apply to create the ElevenLabs tool.")
            print(json.dumps(redact_payload(payload), indent=2))
            return 0
        result = create_tool(api_key, payload)
        print(json.dumps(redact_payload(result), indent=2))
        print("Attach this tool ID to the Orientation and Gap Fill workflow nodes.")
        return 0
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Tool creation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
