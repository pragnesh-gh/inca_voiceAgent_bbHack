from __future__ import annotations

import csv
import json
import shutil
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


SCORE_KEYS = (
    "human_likeness",
    "emotional_fit",
    "claims_competence",
    "checklist_feel",
    "latency_tolerance",
    "language_handling",
)


@dataclass(frozen=True)
class TranscriptTurn:
    speaker: str
    text: str
    time_in_call_secs: float | None = None
    elapsed_ms: float | None = None


@dataclass(frozen=True)
class JuryResult:
    verdict: str
    confidence: float
    scores: dict[str, float]
    reasoning: str
    suggested_improvements: list[str]


@dataclass(frozen=True)
class EvaluationResult:
    trace_dir: str
    summary: dict[str, Any]
    latency_board: dict[str, Any]
    artifacts: dict[str, str]


JudgeFunc = Callable[[str, str, str], JuryResult]


def load_transcript_turns(trace_dir: str | Path) -> list[TranscriptTurn]:
    path = Path(trace_dir) / "transcript.jsonl"
    turns: list[TranscriptTurn] = []
    if not path.exists():
        return turns
    for row in _read_jsonl(path):
        turns.append(
            TranscriptTurn(
                speaker=str(row.get("speaker") or "unknown"),
                text=str(row.get("text") or "").strip(),
                time_in_call_secs=_to_float(row.get("time_in_call_secs")),
                elapsed_ms=_to_float(row.get("elapsed_ms")),
            )
        )
    return [turn for turn in turns if turn.text]


def compute_latency_board(trace_dir: str | Path) -> dict[str, Any]:
    trace = Path(trace_dir)
    turns = load_transcript_turns(trace)
    gaps: list[float] = []
    for index, turn in enumerate(turns):
        if turn.speaker != "user" or turn.time_in_call_secs is None:
            continue
        for next_turn in turns[index + 1 :]:
            if next_turn.speaker == "assistant" and next_turn.time_in_call_secs is not None:
                gap = next_turn.time_in_call_secs - turn.time_in_call_secs
                if gap >= 0:
                    gaps.append(round(gap, 3))
                break

    tool_rows = list(_read_jsonl(trace / "tools.jsonl"))
    return {
        "trace_id": trace.name,
        "user_turn_count": sum(1 for turn in turns if turn.speaker == "user"),
        "assistant_turn_count": sum(1 for turn in turns if turn.speaker == "assistant"),
        "response_gap_count": len(gaps),
        "avg_response_gap_secs": _round(statistics.mean(gaps)) if gaps else None,
        "median_response_gap_secs": _round(statistics.median(gaps)) if gaps else None,
        "max_response_gap_secs": _round(max(gaps)) if gaps else None,
        "response_gaps_secs": gaps,
        "tool_call_count": len(tool_rows),
        "tool_success_count": sum(1 for row in tool_rows if row.get("ok") is True),
        "tool_error_count": sum(1 for row in tool_rows if row.get("ok") is False),
        "tools": [
            {
                "tool": row.get("tool"),
                "ok": row.get("ok"),
                "elapsed_ms": row.get("elapsed_ms"),
                "error": row.get("error"),
            }
            for row in tool_rows
        ],
        "documentation_completion_score": _completion_score(trace),
    }


def aggregate_jury_results(results: list[JuryResult]) -> dict[str, Any]:
    runs = len(results)
    human_votes = sum(1 for result in results if result.verdict.casefold() == "human")
    ai_votes = sum(1 for result in results if result.verdict.casefold() == "ai")
    mean_scores = {
        key: _round(statistics.mean(float(result.scores.get(key, 0.0)) for result in results)) if results else 0.0
        for key in SCORE_KEYS
    }
    suggestions: dict[str, int] = {}
    for result in results:
        for suggestion in result.suggested_improvements:
            clean = suggestion.strip()
            if clean:
                suggestions[clean] = suggestions.get(clean, 0) + 1
    return {
        "runs": runs,
        "human_votes": human_votes,
        "ai_votes": ai_votes,
        "human_vote_rate": human_votes / runs if runs else 0.0,
        "ai_vote_rate": ai_votes / runs if runs else 0.0,
        "mean_confidence": _round(statistics.mean(result.confidence for result in results)) if results else 0.0,
        "mean_scores": mean_scores,
        "top_suggested_improvements": [
            item for item, _count in sorted(suggestions.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
        ],
    }


def evaluate_trace(
    trace_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
    runs: int = 20,
    model: str = "gemini-2.5-pro",
    google_api_key: str | None,
    judge_func: JudgeFunc | None = None,
    history_path: str | Path | None = None,
) -> EvaluationResult:
    if runs < 1:
        raise ValueError("runs must be at least 1")
    if judge_func is None and not google_api_key:
        raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY is required for jury simulation")

    trace = Path(trace_dir)
    out = Path(output_dir or trace)
    turns = load_transcript_turns(trace)
    latency = compute_latency_board(trace)
    transcript_text = _format_transcript(turns)
    latency_text = json.dumps(latency, ensure_ascii=False, indent=2)
    judge = judge_func or judge_with_gemini
    results = [
        judge(_jury_prompt(transcript_text, latency_text, run_index=index + 1, total_runs=runs), model, google_api_key or "")
        for index in range(runs)
    ]
    summary = aggregate_jury_results(results)
    out.mkdir(parents=True, exist_ok=True)

    artifacts = _write_evaluation_artifacts(out, trace, model, results, summary, latency)
    _write_latest_artifacts(trace.parent, artifacts)
    _append_history(
        Path(history_path) if history_path else trace.parent / "eval_runs.csv",
        trace,
        model,
        summary,
        latency,
    )
    return EvaluationResult(str(trace), summary, latency, artifacts)


def judge_with_gemini(prompt: str, model: str, api_key: str) -> JuryResult:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.75,
            response_mime_type="application/json",
        ),
    )
    return jury_result_from_json(_response_text(response))


def jury_result_from_json(raw: str | dict[str, Any]) -> JuryResult:
    payload = raw if isinstance(raw, dict) else json.loads(raw)
    verdict = str(payload.get("verdict") or "").casefold()
    if verdict not in {"human", "ai"}:
        raise ValueError(f"invalid jury verdict: {verdict!r}")
    confidence = min(max(float(payload.get("confidence") or 0.0), 0.0), 1.0)
    scores = payload.get("scores") or {}
    clean_scores = {key: min(max(float(scores.get(key, 0.0)), 0.0), 10.0) for key in SCORE_KEYS}
    improvements = payload.get("suggested_improvements") or []
    return JuryResult(
        verdict=verdict,
        confidence=confidence,
        scores=clean_scores,
        reasoning=str(payload.get("reasoning") or "").strip(),
        suggested_improvements=[str(item).strip() for item in improvements[:3] if str(item).strip()],
    )


def render_jury_summary(trace: Path, model: str, summary: dict[str, Any], latency: dict[str, Any]) -> str:
    scores = summary.get("mean_scores", {})
    improvements = summary.get("top_suggested_improvements") or []
    lines = [
        "# Jury Simulator Summary",
        "",
        f"Trace: `{trace.name}`",
        f"Model: `{model}`",
        f"Runs: {summary['runs']}",
        f"Human vote rate: {summary['human_vote_rate']:.0%}",
        f"AI vote rate: {summary['ai_vote_rate']:.0%}",
        "",
        "## Mean Scores",
        "",
        "| Dimension | Score |",
        "| --- | ---: |",
    ]
    for key in SCORE_KEYS:
        lines.append(f"| {key.replace('_', ' ').title()} | {float(scores.get(key, 0.0)):.1f}/10 |")
    lines.extend(
        [
            "",
            "## Latency Board",
            "",
            f"- User turns: {latency['user_turn_count']}",
            f"- Assistant turns: {latency['assistant_turn_count']}",
            f"- Average response gap: {_display_secs(latency['avg_response_gap_secs'])}",
            f"- Longest response gap: {_display_secs(latency['max_response_gap_secs'])}",
            f"- Tool calls: {latency['tool_call_count']}",
            f"- Documentation completion: {_display_percent(latency['documentation_completion_score'])}",
            "",
            "## Suggested Improvements",
            "",
        ]
    )
    if improvements:
        lines.extend(f"- {item}" for item in improvements)
    else:
        lines.append("- None")
    return "\n".join(lines).strip() + "\n"


def _write_evaluation_artifacts(
    out: Path,
    trace: Path,
    model: str,
    results: list[JuryResult],
    summary: dict[str, Any],
    latency: dict[str, Any],
) -> dict[str, str]:
    scores_json = out / "jury_scores.json"
    scores_csv = out / "jury_scores.csv"
    summary_md = out / "jury_summary.md"
    latency_json = out / "latency_board.json"
    latency_csv = out / "latency_board.csv"

    scores_json.write_text(json.dumps([asdict(result) for result in results], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_jury_scores_csv(scores_csv, results)
    summary_md.write_text(render_jury_summary(trace, model, summary, latency), encoding="utf-8")
    latency_json.write_text(json.dumps(latency, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_latency_csv(latency_csv, latency)
    return {
        "jury_scores_json": str(scores_json),
        "jury_scores_csv": str(scores_csv),
        "jury_summary_md": str(summary_md),
        "latency_board_json": str(latency_json),
        "latency_board_csv": str(latency_csv),
    }


def _write_latest_artifacts(trace_root: Path, artifacts: dict[str, str]) -> None:
    mapping = {
        "jury_scores_json": "LATEST_JURY_SCORES.json",
        "jury_scores_csv": "LATEST_JURY_SCORES.csv",
        "jury_summary_md": "LATEST_JURY_SUMMARY.md",
        "latency_board_json": "LATEST_LATENCY_BOARD.json",
        "latency_board_csv": "LATEST_LATENCY_BOARD.csv",
    }
    root = trace_root.resolve()
    for key, latest_name in mapping.items():
        source = Path(artifacts[key])
        if source.exists():
            source_resolved = source.resolve()
            if not source_resolved.is_relative_to(root):
                raise ValueError(f"artifact source is outside trace root: {source}")
            shutil.copyfile(source_resolved, root / latest_name)


def _append_history(path: Path, trace: Path, model: str, summary: dict[str, Any], latency: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    fields = [
        "timestamp",
        "trace_id",
        "model",
        "runs",
        "human_vote_rate",
        "ai_vote_rate",
        "mean_human_likeness",
        "mean_checklist_feel",
        "avg_response_gap_secs",
        "max_response_gap_secs",
        "documentation_completion_score",
    ]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not exists:
            writer.writeheader()
        scores = summary.get("mean_scores", {})
        writer.writerow(
            {
                "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                "trace_id": trace.name,
                "model": model,
                "runs": summary["runs"],
                "human_vote_rate": _round(summary["human_vote_rate"]),
                "ai_vote_rate": _round(summary["ai_vote_rate"]),
                "mean_human_likeness": scores.get("human_likeness"),
                "mean_checklist_feel": scores.get("checklist_feel"),
                "avg_response_gap_secs": latency.get("avg_response_gap_secs"),
                "max_response_gap_secs": latency.get("max_response_gap_secs"),
                "documentation_completion_score": latency.get("documentation_completion_score"),
            }
        )


def _write_jury_scores_csv(path: Path, results: list[JuryResult]) -> None:
    fields = ["run", "verdict", "confidence", *SCORE_KEYS, "reasoning", "suggested_improvements"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, result in enumerate(results, start=1):
            writer.writerow(
                {
                    "run": index,
                    "verdict": result.verdict,
                    "confidence": result.confidence,
                    **{key: result.scores.get(key) for key in SCORE_KEYS},
                    "reasoning": result.reasoning,
                    "suggested_improvements": " | ".join(result.suggested_improvements),
                }
            )


def _write_latency_csv(path: Path, latency: dict[str, Any]) -> None:
    scalar_keys = [
        "trace_id",
        "user_turn_count",
        "assistant_turn_count",
        "response_gap_count",
        "avg_response_gap_secs",
        "median_response_gap_secs",
        "max_response_gap_secs",
        "tool_call_count",
        "tool_success_count",
        "tool_error_count",
        "documentation_completion_score",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=scalar_keys)
        writer.writeheader()
        writer.writerow({key: latency.get(key) for key in scalar_keys})


def _jury_prompt(transcript: str, latency: str, *, run_index: int, total_runs: int) -> str:
    return (
        "You are simulating one blind hackathon juror calling an insurance claims line. "
        "Judge whether the caller would vote this agent human or AI. Use only the transcript "
        "and latency board. Be strict about AI tells: checklist energy, unnatural phrasing, "
        "bad emotional fit, weird repetition, language confusion, and awkward pauses.\n\n"
        f"Simulation run: {run_index}/{total_runs}\n\n"
        "Return JSON only with this shape:\n"
        "{\n"
        '  "verdict": "human" | "ai",\n'
        '  "confidence": 0.0,\n'
        '  "scores": {\n'
        '    "human_likeness": 0,\n'
        '    "emotional_fit": 0,\n'
        '    "claims_competence": 0,\n'
        '    "checklist_feel": 0,\n'
        '    "latency_tolerance": 0,\n'
        '    "language_handling": 0\n'
        "  },\n"
        '  "reasoning": "short reason",\n'
        '  "suggested_improvements": ["one", "two"]\n'
        "}\n\n"
        "Transcript:\n"
        f"{transcript}\n\n"
        "Latency board:\n"
        f"{latency}"
    )


def _format_transcript(turns: list[TranscriptTurn]) -> str:
    lines = []
    for index, turn in enumerate(turns, start=1):
        timestamp = f"{turn.time_in_call_secs:.1f}s" if turn.time_in_call_secs is not None else "unknown"
        lines.append(f"{index}. [{timestamp}] {turn.speaker}: {turn.text}")
    return "\n".join(lines)


def _completion_score(trace: Path) -> float | None:
    path = trace / "claim_state.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = payload.get("metadata", {}).get("quality", {}).get("completion_score")
        return _round(float(value)) if value is not None else None
    except Exception:
        return None


def _read_jsonl(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return text
    candidates = getattr(response, "candidates", None) or []
    if candidates:
        parts = getattr(getattr(candidates[0], "content", None), "parts", None) or []
        return "".join(str(getattr(part, "text", "")) for part in parts)
    raise ValueError("Gemini response did not include text")


def _display_secs(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1f}s"


def _display_percent(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.0%}"


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float) -> float:
    return round(float(value), 3)
