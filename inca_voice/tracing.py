from __future__ import annotations

import json
import traceback
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any


class CallTrace:
    def __init__(self, call_sid: str, *, trace_root: str = "traces") -> None:
        self.call_sid = safe_id(call_sid or "unknown-call")
        self.started_at = now_iso()
        self._started = monotonic()
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        self.dir = Path(trace_root) / f"{stamp}-{self.call_sid}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.dir / "events.jsonl"
        self.transcript_path = self.dir / "transcript.jsonl"
        self.errors_path = self.dir / "errors.jsonl"
        self.claim_state_path = self.dir / "claim_state.json"
        self.claim_note_path = self.dir / "claim_note.md"
        self.event("trace_started")

    def event(self, event: str, **fields: Any) -> None:
        self._write_jsonl(
            self.events_path,
            {
                "ts": now_iso(),
                "elapsed_ms": self.elapsed_ms,
                "call_sid": self.call_sid,
                "event": event,
                **json_safe(fields),
            },
        )

    def transcript(self, speaker: str, text: str, **fields: Any) -> dict[str, Any]:
        payload = {
            "ts": now_iso(),
            "elapsed_ms": self.elapsed_ms,
            "call_sid": self.call_sid,
            "speaker": speaker,
            "text": text,
            **json_safe(fields),
        }
        self._write_jsonl(self.transcript_path, payload)
        return payload

    def error(self, where: str, exc: BaseException | str, **fields: Any) -> None:
        payload: dict[str, Any] = {
            "ts": now_iso(),
            "elapsed_ms": self.elapsed_ms,
            "call_sid": self.call_sid,
            "where": where,
            **json_safe(fields),
        }
        if isinstance(exc, BaseException):
            payload.update(
                {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                    "traceback": "".join(
                        traceback.format_exception(exc.__class__, exc, exc.__traceback__)
                    ),
                }
            )
        else:
            payload["message"] = exc
        self._write_jsonl(self.errors_path, payload)

    def save_claim_state(self, state: dict[str, Any]) -> None:
        self.claim_state_path.write_text(
            json.dumps(json_safe(state), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def save_claim_note(self, text: str) -> None:
        self.claim_note_path.write_text(text.strip() + "\n", encoding="utf-8")

    @property
    def elapsed_ms(self) -> float:
        return round((monotonic() - self._started) * 1000, 1)

    @staticmethod
    def _write_jsonl(path: Path, payload: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)[:120]


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
