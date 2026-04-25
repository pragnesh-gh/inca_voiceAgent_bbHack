"""Delete the broken LiveKit inbound trunk + dispatch rule, recreate them
with the phone number attached and the agent dispatch wired in.

Twilio side is already configured by setup_twilio_livekit_sip.py --apply.
This script only fixes the LiveKit side.
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from livekit import api


PHONE_NUMBER = "+493042431879"
TRUNK_NAME = "Twilio inbound"
RULE_NAME = "Twilio inbound calls"
ROOM_PREFIX = "phone-"
AGENT_NAME = "inca-claims-agent"


def pick(svc, *names):
    for n in names:
        fn = getattr(svc, n, None)
        if fn is not None:
            return fn
    raise AttributeError(f"none of {names} found on {svc!r}")


async def main() -> None:
    load_dotenv()
    lk = api.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"],
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )
    sip = lk.sip
    list_rules = pick(sip, "list_sip_dispatch_rule", "list_dispatch_rule")
    delete_rule = pick(sip, "delete_sip_dispatch_rule", "delete_dispatch_rule")
    list_trunks = pick(sip, "list_sip_inbound_trunk", "list_inbound_trunk")
    delete_trunk = pick(sip, "delete_sip_trunk", "delete_trunk")
    create_trunk = pick(sip, "create_sip_inbound_trunk", "create_inbound_trunk")
    create_rule = pick(sip, "create_sip_dispatch_rule", "create_dispatch_rule")

    try:
        rules = await list_rules(api.ListSIPDispatchRuleRequest())
        for r in rules.items:
            agents_on_rule = [a.agent_name for a in r.room_config.agents]
            print(
                f"[rule] id={r.sip_dispatch_rule_id} name={r.name!r} "
                f"trunks={list(r.trunk_ids)} agents={agents_on_rule}"
            )
            await delete_rule(
                api.DeleteSIPDispatchRuleRequest(
                    sip_dispatch_rule_id=r.sip_dispatch_rule_id
                )
            )
            print("  deleted")

        trunks = await list_trunks(api.ListSIPInboundTrunkRequest())
        for t in trunks.items:
            print(
                f"[trunk] id={t.sip_trunk_id} name={t.name!r} "
                f"numbers={list(t.numbers)}"
            )
            await delete_trunk(
                api.DeleteSIPTrunkRequest(sip_trunk_id=t.sip_trunk_id)
            )
            print("  deleted")

        trunk = await create_trunk(
            api.CreateSIPInboundTrunkRequest(
                trunk=api.SIPInboundTrunkInfo(
                    name=TRUNK_NAME,
                    numbers=[PHONE_NUMBER],
                )
            )
        )
        print(
            f"created trunk: id={trunk.sip_trunk_id} numbers={list(trunk.numbers)}"
        )

        rule = await create_rule(
            api.CreateSIPDispatchRuleRequest(
                name=RULE_NAME,
                trunk_ids=[trunk.sip_trunk_id],
                rule=api.SIPDispatchRule(
                    dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                        room_prefix=ROOM_PREFIX,
                    )
                ),
                room_config=api.RoomConfiguration(
                    agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME)],
                ),
            )
        )
        print(
            f"created rule: id={rule.sip_dispatch_rule_id} "
            f"trunks={list(rule.trunk_ids)} "
            f"agents={[a.agent_name for a in rule.room_config.agents]}"
        )
    finally:
        await lk.aclose()


if __name__ == "__main__":
    asyncio.run(main())
