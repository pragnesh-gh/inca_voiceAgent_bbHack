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
    return f"{base}/tools/get-call-context"


def build_tool_config(public_url: str, tool_token: str | None) -> dict[str, object]:
    request_headers = {}
    if tool_token:
        request_headers["X-Tool-Token"] = tool_token
    return {
        "tool_config": {
            "type": "webhook",
            "name": "get_call_context",
            "description": (
                "Retrieves non-blocking background context for this call, such as caller area hint "
                "and broad traffic/weather context. Use only after the caller has given enough loss "
                "context or when a small local context check would genuinely help."
            ),
            "response_timeout_secs": 5,
            "disable_interruptions": False,
            "force_pre_tool_speech": True,
            "tool_call_sound_behavior": "auto",
            "api_schema": {
                "url": public_url,
                "method": "POST",
                "path_params_schema": {},
                "request_body_schema": {
                    "type": "object",
                    "required": ["twilio_call_sid"],
                    "description": "Fetch cached background context for the current Twilio call.",
                    "properties": {
                        "twilio_call_sid": {
                            "type": "string",
                            "description": "Twilio call SID. Use the dynamic variable or system call SID for this conversation.",
                        }
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
    parser = argparse.ArgumentParser(description="Create the ElevenLabs get_call_context server tool.")
    parser.add_argument("--apply", action="store_true", help="Actually create the tool in ElevenLabs.")
    args = parser.parse_args()

    load_dotenv(override=True)
    try:
        api_key = require_env("ELEVENLABS_API_KEY")
        public_url = normalize_public_url(require_env("PUBLIC_BASE_URL", "PUBLIC_URL"))
        payload = build_tool_config(public_url, env_first("CALL_CONTEXT_TOOL_TOKEN", "ELEVENLABS_TOOL_TOKEN"))
        print("Plan")
        print(f"  Tool name: {payload['tool_config']['name']}")
        print(f"  Webhook URL: {public_url}")
        print(f"  Tool token header: {'SET' if env_first('CALL_CONTEXT_TOOL_TOKEN', 'ELEVENLABS_TOOL_TOKEN') else 'not set'}")
        if not args.apply:
            print("Dry run only. Add --apply to create the ElevenLabs tool.")
            print(json.dumps(redact_payload(payload), indent=2))
            return 0
        result = create_tool(api_key, payload)
        print(json.dumps(redact_payload(result), indent=2))
        print("Attach this tool to the Gap Fill node. Configure twilio_call_sid from {{twilio_call_sid}} or system call SID.")
        return 0
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Tool creation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
