from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
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


def patch_agent_workflow(agent_id: str, api_key: str, workflow: dict[str, object], *, apply: bool) -> None:
    if not apply:
        print("Dry run only. Add --apply to update ElevenLabs.")
        return

    body = json.dumps({"workflow": workflow}).encode("utf-8")
    req = request.Request(
        f"{API_BASE}/agents/{agent_id}",
        data=body,
        method="PATCH",
        headers={
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        },
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            print(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ElevenLabs API {exc.code}: {text}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch the ElevenLabs agent workflow from a local JSON file.")
    parser.add_argument(
        "--workflow",
        default="docs/elevenlabs-claims-workflow.json",
        help="Path to workflow JSON.",
    )
    parser.add_argument("--apply", action="store_true", help="Actually update ElevenLabs.")
    args = parser.parse_args()

    load_dotenv(override=True)
    try:
        agent_id = require_env("ELEVENLABS_AGENT_ID")
        api_key = require_env("ELEVENLABS_API_KEY")
        workflow_path = Path(args.workflow)
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        print("Plan")
        print(f"  Agent ID: {agent_id}")
        print(f"  Workflow: {workflow_path}")
        print(f"  Nodes: {len(workflow.get('nodes', {}))}")
        print(f"  Edges: {len(workflow.get('edges', {}))}")
        patch_agent_workflow(agent_id, api_key, workflow, apply=args.apply)
        return 0
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Workflow update failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
