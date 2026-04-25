import asyncio
import random
from datetime import datetime
from typing import Any

from livekit.agents import RunContext, function_tool
from tools.stalling import say_stalling_phrase


async def _lookup_delay() -> None:
    await asyncio.sleep(random.uniform(0.3, 0.8))


@function_tool()
async def check_claim_status(context: RunContext, claim_id: str) -> dict[str, Any]:
    """Look up the mock status of an existing auto insurance claim.

    Args:
        claim_id: Claim reference number provided by the caller.
    """
    await say_stalling_phrase(context)
    await _lookup_delay()

    normalized_id = claim_id.strip().upper().replace(" ", "").replace("-", "")
    if not normalized_id:
        normalized_id = "MMCLM000000"

    known_claims: dict[str, dict[str, Any]] = {
        "MMCLM202604250173": {
            "claim_id": "MM-CLM-20260425-0173",
            "policy_id": "MM-AUTO-4831",
            "status": "awaiting_documents",
            "status_label": "waiting for photos and the police reference",
            "loss_type": "parking damage",
            "incident_date": "2026-04-24",
            "assigned_adjuster": "Stefanie Kuehne",
            "next_step": "Upload damage photos and the police case number.",
            "last_updated": "2026-04-25T09:20:00+02:00",
        },
        "MMCLM202604240912": {
            "claim_id": "MM-CLM-20260424-0912",
            "policy_id": "MM-AUTO-9184",
            "status": "repair_authorized",
            "status_label": "network repair authorized",
            "loss_type": "glass damage",
            "incident_date": "2026-04-23",
            "assigned_adjuster": "Stefanie Kuehne",
            "next_step": "The network glass shop can bill Meridian Mutual directly.",
            "last_updated": "2026-04-24T16:45:00+02:00",
        },
    }

    if normalized_id in known_claims:
        return {"found": True, **known_claims[normalized_id]}

    ending = normalized_id[-4:].rjust(4, "0")
    status_options = [
        ("received", "received, not assigned yet", "A claims handler will review it next."),
        ("coverage_review", "under coverage review", "We are checking coverage and liability details."),
        ("awaiting_documents", "waiting for documents", "Send photos, repair estimate, or police reference if available."),
    ]
    status, status_label, next_step = status_options[int(ending[-1]) % len(status_options)]
    return {
        "found": True,
        "claim_id": claim_id.strip() or f"MM-CLM-20260425-{ending}",
        "policy_id": f"MM-AUTO-{ending}",
        "status": status,
        "status_label": status_label,
        "loss_type": "auto claim",
        "incident_date": "2026-04-24",
        "assigned_adjuster": "Stefanie Kuehne",
        "next_step": next_step,
        "last_updated": "2026-04-25T12:10:00+02:00",
    }


@function_tool()
async def file_new_claim(context: RunContext, policy_id: str, description: str, incident_date: str) -> dict[str, Any]:
    """File a mock first notice of loss for an auto claim.

    Args:
        policy_id: Policy ID for the caller's auto policy.
        description: Short natural-language description of what happened.
        incident_date: Date of loss as provided by the caller.
    """
    await say_stalling_phrase(context)
    await _lookup_delay()

    today = datetime.now().astimezone().strftime("%Y%m%d")
    claim_suffix = random.randint(1000, 9999)
    return {
        "claim_id": f"MM-CLM-{today}-{claim_suffix}",
        "policy_id": policy_id.strip(),
        "status": "received",
        "status_label": "claim received",
        "incident_date": incident_date.strip(),
        "description": description.strip(),
        "next_step": "A claims handler will review the file and call back if anything is missing.",
    }
