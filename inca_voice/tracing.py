from __future__ import annotations

import json
import traceback
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any


class CallTrace:
    def __init__(self, call_sid: str, *, trace_root: str = "traces", label: str | None = None) -> None:
        self.call_sid = safe_id(call_sid or "unknown-call")
        self.started_at = now_iso()
        self._started = monotonic()
        self.root = Path(trace_root)
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
        label_part = safe_id(label or "call")
        self.dir = self.root / f"{stamp}_{label_part}_{self.call_sid}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.dir / "events.jsonl"
        self.transcript_path = self.dir / "transcript.jsonl"
        self.errors_path = self.dir / "errors.jsonl"
        self.tools_path = self.dir / "tools.jsonl"
        self.claim_state_path = self.dir / "claim_state.json"
        self.claim_note_path = self.dir / "claim_note.md"
        self.loss_notice_path = self.dir / f"FNOL_AutoLossNotice_{self.call_sid}.md"
        self.redacted_loss_notice_path = self.dir / f"FNOL_AutoLossNotice_{self.call_sid}_REDACTED.md"
        self.redacted_pdf_path = self.dir / f"FNOL_AutoLossNotice_{self.call_sid}_REDACTED.pdf"
        self.callback_ics_path = self.dir / f"FNOL_Callback_{self.call_sid}.ics"
        self.latest_trace_path = self.root / "LATEST_TRACE_DIR.txt"
        self.latest_state_path = self.root / "LATEST_CLAIM_STATE.json"
        self.latest_note_path = self.root / "LATEST_CLAIM_NOTE.md"
        self.latest_loss_notice_path = self.root / "LATEST_FNOL_AUTO_LOSS_NOTICE.md"
        self.latest_redacted_loss_notice_path = self.root / "LATEST_FNOL_AUTO_LOSS_NOTICE_REDACTED.md"
        self.latest_redacted_pdf_path = self.root / "LATEST_FNOL_AUTO_LOSS_NOTICE_REDACTED.pdf"
        self.latest_callback_ics_path = self.root / "LATEST_FNOL_CALLBACK.ics"
        self.event("trace_started")
        self._write_latest_trace()

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

    def tool_call(
        self,
        tool: str,
        *,
        request_summary: dict[str, Any] | None = None,
        response_summary: dict[str, Any] | None = None,
        ok: bool,
        error: str | None = None,
    ) -> None:
        self._write_jsonl(
            self.tools_path,
            {
                "ts": now_iso(),
                "elapsed_ms": self.elapsed_ms,
                "call_sid": self.call_sid,
                "tool": tool,
                "ok": ok,
                "request_summary": json_safe(request_summary or {}),
                "response_summary": json_safe(response_summary or {}),
                "error": error,
            },
        )

    def save_claim_state(self, state: dict[str, Any]) -> None:
        content = json.dumps(json_safe(state), indent=2, ensure_ascii=False) + "\n"
        self.claim_state_path.write_text(content, encoding="utf-8")
        self.latest_state_path.write_text(content, encoding="utf-8")
        self._write_latest_trace()

    def save_claim_note(self, text: str) -> None:
        content = text.strip() + "\n"
        self.claim_note_path.write_text(content, encoding="utf-8")
        self.loss_notice_path.write_text(content, encoding="utf-8")
        self.latest_note_path.write_text(content, encoding="utf-8")
        self.latest_loss_notice_path.write_text(content, encoding="utf-8")
        self._write_latest_trace()

    def save_redacted_claim_note(self, text: str) -> None:
        content = text.strip() + "\n"
        self.redacted_loss_notice_path.write_text(content, encoding="utf-8")
        self.latest_redacted_loss_notice_path.write_text(content, encoding="utf-8")
        self._write_latest_trace()

    def save_callback_ics(self, text: str) -> None:
        self.callback_ics_path.write_text(text, encoding="utf-8")
        self.latest_callback_ics_path.write_text(text, encoding="utf-8")
        self._write_latest_trace()

    def _write_latest_trace(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.latest_trace_path.write_text(str(self.dir.resolve()) + "\n", encoding="utf-8")

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
