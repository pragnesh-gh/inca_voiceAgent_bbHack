from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inca_voice.config import load_settings
from inca_voice.jury_evaluator import evaluate_trace


def main() -> int:
    parser = argparse.ArgumentParser(description="Run transcript jury simulation and latency board for a call trace.")
    parser.add_argument("--trace-dir", help="Trace directory to evaluate. Defaults to traces/LATEST_TRACE_DIR.txt.")
    parser.add_argument("--runs", type=int, default=20, help="Number of simulated jurors to run. Default: 20.")
    parser.add_argument("--model", default="gemini-2.5-pro", help="Gemini model for the jury simulator.")
    parser.add_argument("--output-dir", help="Directory for evaluator artifacts. Defaults to the trace directory.")
    args = parser.parse_args()

    load_dotenv(override=True)
    settings = load_settings()
    trace_dir = Path(args.trace_dir) if args.trace_dir else _latest_trace_dir(settings.trace_dir)
    try:
        result = evaluate_trace(
            trace_dir,
            output_dir=Path(args.output_dir) if args.output_dir else trace_dir,
            runs=args.runs,
            model=args.model,
            google_api_key=settings.google_api_key,
        )
    except Exception as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1

    print("Jury simulator complete")
    print(f"  Trace: {result.trace_dir}")
    print(f"  Runs: {result.summary['runs']}")
    print(f"  Human vote rate: {result.summary['human_vote_rate']:.0%}")
    print(f"  AI vote rate: {result.summary['ai_vote_rate']:.0%}")
    print(f"  Avg response gap: {_display(result.latency_board.get('avg_response_gap_secs'))}")
    print(f"  Longest response gap: {_display(result.latency_board.get('max_response_gap_secs'))}")
    print(f"  Summary: {result.artifacts['jury_summary_md']}")
    return 0


def _latest_trace_dir(trace_root: str) -> Path:
    latest = Path(trace_root) / "LATEST_TRACE_DIR.txt"
    if not latest.exists():
        raise FileNotFoundError(f"No latest trace found at {latest}")
    value = latest.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"{latest} is empty")
    return Path(value)


def _display(value) -> str:
    return "n/a" if value is None else f"{float(value):.1f}s"


if __name__ == "__main__":
    raise SystemExit(main())
