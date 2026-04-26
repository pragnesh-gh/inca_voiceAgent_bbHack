import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from inca_voice.callback_ics import build_callback_ics
from inca_voice.fnol_schema import (
    CallbackRequest,
    FNOLDocument,
    FNOLField,
    PolicyMatch,
    QualityReport,
    TimelineEvent,
)
from inca_voice.pdf_render import render_fnol_pdf
from inca_voice.redaction import redact_markdown
from inca_voice.tracing import CallTrace


class DocumentationArtifactTests(unittest.TestCase):
    def test_fnol_schema_accepts_valid_document_and_rejects_bad_confidence(self):
        doc = sample_fnol_document()

        self.assertEqual(doc.policy_match.policy_number.value, "MM-KFZ-4831")
        self.assertEqual(doc.timeline[0].event_type, "safety")

        with self.assertRaises(ValueError):
            FNOLField(value="bad", confidence=1.5, source_turn_ids=[1], needs_followup=False)

    def test_redaction_masks_pii_but_preserves_context(self):
        raw = (
            "Policy MM-KFZ-4831 for Pragnesh, DOB 2001-10-26, phone +4915510823559, "
            "email pragnesh.pallaprolu@example.test, plate B-PK-2601, VIN WVWZZZ1KZ8W483101, "
            "address Karl-Liebknecht-Strasse 12, 10178 Berlin."
        )

        redacted = redact_markdown(raw)

        self.assertNotIn("MM-KFZ-4831", redacted)
        self.assertNotIn("2001-10-26", redacted)
        self.assertNotIn("+4915510823559", redacted)
        self.assertNotIn("pragnesh.pallaprolu@example.test", redacted)
        self.assertNotIn("B-PK-2601", redacted)
        self.assertNotIn("WVWZZZ1KZ8W483101", redacted)
        self.assertIn("[POLICY]", redacted)
        self.assertIn("[DOB]", redacted)
        self.assertIn("Berlin", redacted)

    def test_pdf_renderer_creates_non_empty_pdf(self):
        out_dir = Path("tmp-test-traces") / uuid4().hex
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = out_dir / "fnol.pdf"

        render_fnol_pdf("# FNOL Auto Loss Notice\n\n## Summary\nA short summary.", pdf_path)

        self.assertTrue(pdf_path.exists())
        self.assertGreater(pdf_path.stat().st_size, 500)

    def test_callback_ics_requires_concrete_time(self):
        missing = CallbackRequest(needed=True, requested_time=None, timezone="Europe/Berlin", notes="Call later")
        concrete = CallbackRequest(
            needed=True,
            requested_time=datetime(2026, 4, 27, 10, 30, tzinfo=timezone.utc),
            timezone="Europe/Berlin",
            notes="Discuss police case number",
        )

        self.assertIsNone(build_callback_ics(missing))
        ics = build_callback_ics(concrete)

        self.assertIsNotNone(ics)
        self.assertIn("BEGIN:VCALENDAR", ics)
        self.assertIn("Discuss police case number", ics)

    def test_trace_writes_tool_audit_log(self):
        trace_dir = Path("tmp-test-traces") / uuid4().hex
        trace = CallTrace("CA123", trace_root=str(trace_dir), label="test-call")

        trace.tool_call(
            "lookup_policyholder",
            request_summary={"name": "Pragnesh"},
            response_summary={"matched": True, "policy_number": "MM-KFZ-4831"},
            ok=True,
        )

        tool_rows = (trace.dir / "tools.jsonl").read_text(encoding="utf-8").splitlines()
        payload = json.loads(tool_rows[0])
        self.assertEqual(payload["tool"], "lookup_policyholder")
        self.assertTrue(payload["ok"])


def sample_fnol_document() -> FNOLDocument:
    field = lambda value, confidence=0.8: FNOLField(
        value=value,
        confidence=confidence,
        source_turn_ids=[1],
        needs_followup=False,
    )
    return FNOLDocument(
        document_status="Draft FNOL",
        policy_match=PolicyMatch(
            status="verified",
            confidence=0.9,
            policy_number=field("MM-KFZ-4831"),
            insured_name=field("Pragnesh Kumar Pallaprolu"),
        ),
        executive_summary="Caller reported a single vehicle collision.",
        safety={"safe_location": field(True), "injuries_reported": field(False)},
        caller={"full_name": field("Pragnesh Kumar Pallaprolu")},
        loss={"loss_type": field("collision")},
        people={},
        vehicles={},
        police={},
        witnesses={},
        coverage={},
        evidence={},
        resolution={},
        timeline=[
            TimelineEvent(
                time_in_call_secs=12,
                turn_id=2,
                event_type="safety",
                summary="Caller reported being safe.",
                sentiment="calm",
            )
        ],
        quality=QualityReport(completion_score=0.8, missing_essentials=[], open_questions=[]),
        callback=CallbackRequest(needed=False, requested_time=None, timezone="Europe/Berlin", notes=None),
    )


if __name__ == "__main__":
    unittest.main()
