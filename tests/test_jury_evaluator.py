import csv
import json
import unittest
from pathlib import Path
from uuid import uuid4

from inca_voice.jury_evaluator import (
    JuryResult,
    aggregate_jury_results,
    compute_latency_board,
    evaluate_trace,
    load_transcript_turns,
    _write_evaluation_artifacts,
    _write_latest_artifacts,
)


class JuryEvaluatorTests(unittest.TestCase):
    def test_load_transcript_turns_preserves_order(self):
        with workspace_tmp() as tmp:
            trace = make_trace(tmp)

            turns = load_transcript_turns(trace)

            self.assertEqual([turn.speaker for turn in turns], ["user", "assistant", "user", "assistant"])
            self.assertEqual(turns[0].text, "I had an accident.")
            self.assertEqual(turns[2].time_in_call_secs, 12.0)

    def test_latency_board_computes_user_to_next_assistant_gaps(self):
        with workspace_tmp() as tmp:
            trace = make_trace(tmp)

            board = compute_latency_board(trace)

            self.assertEqual(board["user_turn_count"], 2)
            self.assertEqual(board["assistant_turn_count"], 2)
            self.assertEqual(board["response_gap_count"], 2)
            self.assertEqual(board["avg_response_gap_secs"], 2.0)
            self.assertEqual(board["max_response_gap_secs"], 3.0)
            self.assertEqual(board["tool_call_count"], 1)
            self.assertEqual(board["documentation_completion_score"], 0.75)

    def test_aggregate_jury_results_counts_votes_and_scores(self):
        results = [
            sample_result("human", 0.8, human_likeness=8, checklist_feel=2),
            sample_result("ai", 0.7, human_likeness=4, checklist_feel=7),
            sample_result("human", 0.6, human_likeness=7, checklist_feel=3),
        ]

        summary = aggregate_jury_results(results)

        self.assertEqual(summary["runs"], 3)
        self.assertAlmostEqual(summary["human_vote_rate"], 2 / 3)
        self.assertAlmostEqual(summary["ai_vote_rate"], 1 / 3)
        self.assertAlmostEqual(summary["mean_scores"]["human_likeness"], round(19 / 3, 3))
        self.assertIn("slow lookup", summary["top_suggested_improvements"])

    def test_evaluate_trace_writes_artifacts_and_history(self):
        with workspace_tmp() as root:
            trace = make_trace(root / "trace-a")

            def fake_judge(_prompt, _model, _api_key):
                return sample_result("human", 0.82)

            result = evaluate_trace(
                trace,
                output_dir=trace,
                runs=3,
                model="gemini-2.5-pro",
                google_api_key="test-key",
                judge_func=fake_judge,
                history_path=root / "eval_runs.csv",
            )

            self.assertEqual(result.summary["runs"], 3)
            self.assertTrue((trace / "jury_scores.json").exists())
            self.assertTrue((trace / "jury_scores.csv").exists())
            self.assertTrue((trace / "jury_summary.md").exists())
            self.assertTrue((trace / "latency_board.json").exists())
            self.assertTrue((trace / "latency_board.csv").exists())
            self.assertTrue((root / "LATEST_JURY_SUMMARY.md").exists())
            self.assertTrue((root / "LATEST_LATENCY_BOARD.json").exists())

            evaluate_trace(
                trace,
                output_dir=trace,
                runs=1,
                model="gemini-2.5-pro",
                google_api_key="test-key",
                judge_func=fake_judge,
                history_path=root / "eval_runs.csv",
            )
            with (root / "eval_runs.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["model"], "gemini-2.5-pro")
            self.assertEqual(rows[0]["runs"], "3")

    def test_missing_google_api_key_errors_without_writing_artifacts(self):
        with workspace_tmp() as tmp:
            trace = make_trace(tmp)

            with self.assertRaisesRegex(ValueError, "GOOGLE_API_KEY"):
                evaluate_trace(
                    trace,
                    output_dir=trace,
                    runs=1,
                    model="gemini-2.5-pro",
                    google_api_key=None,
                )

            self.assertFalse((trace / "jury_scores.json").exists())

    def test_latest_artifact_copy_rejects_sources_outside_trace_root(self):
        with workspace_tmp() as root:
            trace = make_trace(root / "trace-a")
            out = root / "trace-a"
            result = sample_result("human", 0.82)
            artifacts = _write_evaluation_artifacts(
                out,
                trace,
                "gemini-2.5-pro",
                [result],
                aggregate_jury_results([result]),
                compute_latency_board(trace),
            )
            outside = root.parent / f"escape-{uuid4().hex}.md"
            artifacts["jury_summary_md"] = str(outside)

            outside.write_text("escape attempt", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside trace root"):
                _write_latest_artifacts(root, artifacts)


def make_trace(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    write_jsonl(
        path / "transcript.jsonl",
        [
            {"speaker": "user", "text": "I had an accident.", "time_in_call_secs": 4},
            {"speaker": "assistant", "text": "Oh no, are you safe?", "time_in_call_secs": 5},
            {"speaker": "user", "text": "Yes, I am home now.", "time_in_call_secs": 12},
            {"speaker": "assistant", "text": "Okay, let me get this started.", "time_in_call_secs": 15},
        ],
    )
    write_jsonl(
        path / "tools.jsonl",
        [
            {
                "tool": "lookup_policyholder",
                "ok": True,
                "elapsed_ms": 321,
                "request_summary": {"source": "test"},
                "response_summary": {"matched": True},
            }
        ],
    )
    (path / "claim_state.json").write_text(
        json.dumps({"metadata": {"quality": {"completion_score": 0.75}}}),
        encoding="utf-8",
    )
    return path


class workspace_tmp:
    def __enter__(self) -> Path:
        self.path = Path("tmp-test-traces") / uuid4().hex
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, exc_type, exc, tb):
        return False


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def sample_result(verdict: str, confidence: float, **scores) -> JuryResult:
    base_scores = {
        "human_likeness": 8,
        "emotional_fit": 7,
        "claims_competence": 8,
        "checklist_feel": 2,
        "latency_tolerance": 6,
        "language_handling": 7,
    }
    base_scores.update(scores)
    return JuryResult(
        verdict=verdict,
        confidence=confidence,
        scores=base_scores,
        reasoning="The call felt plausible but had a slow lookup.",
        suggested_improvements=["slow lookup"],
    )


if __name__ == "__main__":
    unittest.main()
