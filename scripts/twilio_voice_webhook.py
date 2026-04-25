from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs
from xml.sax.saxutils import escape


CONFIG_PATH = Path("twilio_voice_webhook.local.json")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8088


def load_config() -> dict[str, str]:
    config: dict[str, str] = {}
    if CONFIG_PATH.exists():
        config.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))

    env_map = {
        "phone_number": "TWILIO_PHONE_NUMBER",
        "sip_endpoint": "LIVEKIT_SIP_ENDPOINT",
        "auth_username": "LIVEKIT_SIP_AUTH_USERNAME",
        "auth_password": "LIVEKIT_SIP_AUTH_PASSWORD",
    }
    for key, env_name in env_map.items():
        if os.getenv(env_name):
            config[key] = os.environ[env_name]

    required = ["phone_number", "sip_endpoint", "auth_username", "auth_password"]
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise RuntimeError(
            "Missing webhook config keys: "
            + ", ".join(missing)
            + ". Run scripts/setup_twilio_voice_webhook.py --apply first."
        )
    return config


def build_twiml(config: dict[str, str]) -> str:
    sip_uri = f"sip:{config['phone_number']}@{config['sip_endpoint']};transport=tcp"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        '<Dial answerOnBridge="true">'
        f'<Sip username="{escape(config["auth_username"])}" '
        f'password="{escape(config["auth_password"])}">'
        f"{escape(sip_uri)}"
        "</Sip>"
        "</Dial>"
        "</Response>"
    )


class TwilioVoiceWebhook(BaseHTTPRequestHandler):
    server_version = "IncaTwilioVoiceWebhook/1.0"

    def do_GET(self) -> None:
        if self.path.startswith("/health"):
            self._send_text("ok\n", content_type="text/plain")
            return
        if self.path.startswith("/twilio/voice"):
            self._send_twiml()
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path.startswith("/twilio/voice"):
            length = int(self.headers.get("content-length", "0") or "0")
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            form = parse_qs(body)
            print(
                "twilio voice webhook",
                {
                    "CallSid": _first(form, "CallSid"),
                    "From": _first(form, "From"),
                    "To": _first(form, "To"),
                    "CallStatus": _first(form, "CallStatus"),
                },
            )
            self._send_twiml()
            return
        self.send_error(404)

    def log_message(self, fmt: str, *args: object) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))

    def _send_twiml(self) -> None:
        try:
            config = load_config()
            self._send_text(build_twiml(config), content_type="text/xml")
        except Exception as exc:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(str(exc).encode("utf-8"))

    def _send_text(self, text: str, *, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _first(form: dict[str, list[str]], key: str) -> str | None:
    values = form.get(key)
    return values[0] if values else None


def main() -> None:
    host = os.getenv("TWILIO_WEBHOOK_HOST", DEFAULT_HOST)
    port = int(os.getenv("TWILIO_WEBHOOK_PORT", str(DEFAULT_PORT)))
    load_config()
    server = ThreadingHTTPServer((host, port), TwilioVoiceWebhook)
    print(f"Twilio voice webhook listening on http://{host}:{port}")
    print("Expose this with an HTTPS tunnel and point Twilio at /twilio/voice")
    server.serve_forever()


if __name__ == "__main__":
    main()
