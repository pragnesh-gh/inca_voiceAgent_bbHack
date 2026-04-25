import asyncio
import random
from typing import Any

from livekit.agents import RunContext, function_tool
from tools.stalling import say_stalling_phrase


async def _lookup_delay() -> None:
    await asyncio.sleep(random.uniform(0.3, 0.8))


@function_tool()
async def lookup_policy(context: RunContext, policy_id: str) -> dict[str, Any]:
    """Look up mock auto insurance policy data by policy number or policy suffix.

    Args:
        policy_id: Full policy ID or the last few digits the caller provides.
    """
    await say_stalling_phrase(context)
    await _lookup_delay()

    normalized_id = policy_id.strip().upper().replace(" ", "").replace("-", "")
    if not normalized_id:
        normalized_id = "UNKNOWN"

    demo_policies: dict[str, dict[str, Any]] = {
        "4831": {
            "policy_id": "MM-AUTO-4831",
            "status": "active",
            "policyholder": {
                "name": "Jonas Wagner",
                "date_of_birth": "1987-04-18",
                "phone": "+49 30 5550 4831",
                "email": "jonas.wagner@example.invalid",
            },
            "address": {
                "street": "Karl-Marx-Allee 72",
                "postal_code": "10243",
                "city": "Berlin",
                "country": "DE",
            },
            "vehicle": {
                "plate": "B-MW 4831",
                "make": "Volkswagen",
                "model": "Golf Variant",
                "year": 2021,
                "vin": "WVWZZZCDZMW04831",
                "garage_address": "Karl-Marx-Allee 72, 10243 Berlin",
            },
            "coverage": {
                "liability": True,
                "partial_casco": {"active": True, "deductible_eur": 150},
                "full_casco": {"active": True, "deductible_eur": 500},
                "roadside_assistance": True,
                "workshop_binding": False,
                "no_claims_class": "SF 11",
            },
            "premium_status": "paid",
            "renewal_date": "2026-10-01",
        },
        "9184": {
            "policy_id": "MM-AUTO-9184",
            "status": "active",
            "policyholder": {
                "name": "Miriam Keller",
                "date_of_birth": "1992-11-03",
                "phone": "+49 30 5550 9184",
                "email": "miriam.keller@example.invalid",
            },
            "address": {
                "street": "Pappelallee 19",
                "postal_code": "10437",
                "city": "Berlin",
                "country": "DE",
            },
            "vehicle": {
                "plate": "B-MK 9184",
                "make": "Toyota",
                "model": "Yaris Hybrid",
                "year": 2023,
                "vin": "JTDKBAC30009184",
                "garage_address": "Pappelallee 19, 10437 Berlin",
            },
            "coverage": {
                "liability": True,
                "partial_casco": {"active": True, "deductible_eur": 150},
                "full_casco": {"active": False, "deductible_eur": None},
                "roadside_assistance": False,
                "workshop_binding": True,
                "no_claims_class": "SF 6",
            },
            "premium_status": "paid",
            "renewal_date": "2027-01-15",
        },
    }

    for suffix, policy in demo_policies.items():
        if normalized_id.endswith(suffix):
            return {"found": True, **policy}

    suffix = normalized_id[-4:].rjust(4, "0")
    return {
        "found": True,
        "policy_id": f"MM-AUTO-{suffix}",
        "status": "active",
        "policyholder": {
            "name": "Alex Schneider",
            "date_of_birth": "1984-09-22",
            "phone": f"+49 30 5550 {suffix}",
            "email": "alex.schneider@example.invalid",
        },
        "address": {
            "street": "Invalidenstrasse 44",
            "postal_code": "10115",
            "city": "Berlin",
            "country": "DE",
        },
        "vehicle": {
            "plate": f"B-AS {suffix}",
            "make": "Skoda",
            "model": "Octavia Combi",
            "year": 2020,
            "vin": f"TMBJJ7NE0L0{suffix}",
            "garage_address": "Invalidenstrasse 44, 10115 Berlin",
        },
        "coverage": {
            "liability": True,
            "partial_casco": {"active": True, "deductible_eur": 150},
            "full_casco": {"active": True, "deductible_eur": 300},
            "roadside_assistance": True,
            "workshop_binding": False,
            "no_claims_class": "SF 8",
        },
        "premium_status": "paid",
        "renewal_date": "2026-12-01",
    }
