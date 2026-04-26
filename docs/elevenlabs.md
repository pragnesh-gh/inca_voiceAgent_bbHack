# ElevenLabs Register-Call Runtime

ElevenLabs is now the primary competition call runtime. Twilio still owns the phone number, but our `/twilio/voice` webhook registers each inbound Twilio call with ElevenLabs and returns the TwiML supplied by ElevenLabs.

Sources:

- ElevenLabs Agents overview: https://elevenlabs.io/docs/eleven-agents/overview
- Twilio native integration: https://elevenlabs.io/docs/eleven-agents/phone-numbers/twilio-integration/native-integration
- Register Twilio calls API: https://elevenlabs.io/docs/eleven-agents/phone-numbers/twilio-integration/register-call
- Conversation flow controls: https://elevenlabs.io/docs/eleven-agents/customization/conversation-flow
- Post-call webhooks: https://elevenlabs.io/docs/eleven-agents/workflows/post-call-webhooks
- Knowledge base: https://elevenlabs.io/docs/eleven-agents/customization/knowledge-base

## Local Runtime

```text
caller phone
  -> Twilio number +493075679047
  -> POST /twilio/voice
  -> ElevenLabs register_call(agent_id, from_number, to_number, direction="inbound")
  <- ElevenLabs TwiML
  -> ElevenLabs handles ASR, turn-taking, interruptions, LLM, TTS, and phone audio
  -> POST /elevenlabs/post-call
  -> ClaimsScribe writes trace artifacts and claim note
```

Required env vars:

```text
USE_ELEVENLABS_REGISTER_CALL=1
ELEVENLABS_API_KEY=
ELEVENLABS_AGENT_ID=
TWILIO_PHONE_NUMBER=+493075679047
```

Optional:

```text
ELEVENLABS_WEBHOOK_SECRET=
POLICYHOLDER_DB_PATH=data/mock_policyholders.csv
POLICY_LOOKUP_TOOL_TOKEN=
```

## Agent Configuration

Configure the ElevenLabs agent in the dashboard with:

- For Register Twilio Calls, set both voice output and ASR input to `mu-law 8000 Hz`. ElevenLabs documents this as required for Twilio. Do not use the generic `PCM 16000 Hz` recommendation for this path.
- Persona: Stefanie Kuehne, introduces herself as "Stefanie".
- Bilingual English/German handling, but default back to English when the caller mixes language.
- CARE-FNOL behavior from `prompts/system.md`.
- Short phone-native replies.
- Interruptions enabled.
- Natural filler/soft-timeout phrases enabled.
- Knowledge base containing policy/FNOL/German insurance notes.
- Server tool `lookup_policyholder` attached to Orientation and Gap Fill for deterministic mock policy lookup.
- Server tool `search_claim_context` attached only if `TAVILY_API_KEY` is set and the public webhook URL is stable.
- Server tool `get_call_context` attached to Gap Fill for non-blocking background context already fetched for this Twilio call.

Do not rely on Knowledge Base alone for policyholder lookup. Knowledge Base is useful for general FNOL guidance and German insurance vocabulary, but caller identity and policy details should come from the webhook tool backed by `data/mock_policyholders.csv`.

## Per-call Dynamic Variables

The Twilio webhook passes these variables to ElevenLabs at call registration time:

```text
caller_number
called_number
twilio_call_sid
agent_name
local_time_de
weekday_de
caller_area_hint
agent_shift_anchor
context_priming_rule
```

Use `{{agent_shift_anchor}}` at most once, only if it naturally fits and never during emergency triage. These anchors are intentionally harmless mood/context lines, not factual claims about the incident.

## Pause Realism Settings

Use dashboard settings for pause realism. ElevenLabs supports tool call sounds and soft-timeout fillers, but does not expose a documented arbitrary live audio-mixing hook for managed Twilio Agents.

Tool call sounds:

- `lookup_policyholder`: set **Tool call sound** to `Typing`.
- `lookup_policyholder`: set behavior to `With pre-speech / Auto` if available, otherwise `Auto`.
- `search_claim_context`: set **Tool call sound** to `Typing`.
- `search_claim_context`: set behavior to `With pre-speech / Auto` if available, otherwise `Auto`.
- Keep pre-tool speech enabled so Stefanie says a short phrase first, such as "One sec" or "Okay, lemme check."

Soft timeout:

- Enable soft timeout / filler behavior in Conversation Flow.
- Start with a timeout of `1.5s`; use `2.0s` if it interrupts too eagerly.
- Static fallback filler: `Mhm, okay.`
- Other safe fillers: `Okay, one moment.`, `Right, let me check.`, `Yeah, got it.`
- Keep turn eagerness at `Normal`; use `Patient` only on detail-heavy nodes if callers are being cut off.

Avoid for now:

- Continuous call-center ambience under the whole call.
- Generated sound effects injected into normal speech.
- Programmatic ElevenLabs tool mutation during demo prep.

## Policyholder Lookup Tool

Local webhook:

```text
POST https://PUBLIC_HOST/tools/lookup-policyholder
```

Body:

```json
{
  "name": "Pragnesh Kumar Pallaprolu",
  "date_of_birth": "2001-10-26",
  "phone": "+4915510823559",
  "policy_number": "MM-KFZ-4831",
  "license_plate": "B-PK-2601"
}
```

Optional header if `POLICY_LOOKUP_TOOL_TOKEN` is set:

```text
X-Tool-Token: <token>
```

Create the ElevenLabs tool from local config with:

```powershell
python scripts\create_elevenlabs_policy_lookup_tool.py
python scripts\create_elevenlabs_policy_lookup_tool.py --apply
```

Attach it to the **Orientation** and **Gap Fill** nodes, not Safety Triage. Stefanie should say a short stalling phrase before using it: "One sec, let me pull that up."

## Tavily Context Tool

The live web tool is intentionally narrow. Configure it as an ElevenLabs server tool only for weather, traffic, roadworks, closures, public events, and location context.

Local webhook:

```text
POST https://PUBLIC_HOST/tools/search-claim-context
```

Body:

```json
{
  "query": "A100 Berlin roadworks today",
  "location": "Berlin A100",
  "incident_time": "today 15:00"
}
```

Optional header if `TAVILY_TOOL_TOKEN` is set:

```text
X-Tool-Token: <token>
```

Do not use this tool for coverage, liability, legal, premium, policy, or fraud decisions.

Create the ElevenLabs tool from the local config with:

```powershell
python scripts\create_elevenlabs_tavily_tool.py
python scripts\create_elevenlabs_tavily_tool.py --apply
```

The script prints the created tool ID. Attach that tool to the Stefanie agent or only to the Gap Fill workflow node.

## Async Call Context Tool

The call answers immediately. Background context enrichment runs after successful ElevenLabs registration and stores cached context by Twilio call SID. The agent can retrieve it later only if useful.

Local webhook:

```text
POST https://PUBLIC_HOST/tools/get-call-context
```

Body:

```json
{
  "twilio_call_sid": "{{twilio_call_sid}}"
}
```

Optional header if `CALL_CONTEXT_TOOL_TOKEN` is set:

```text
X-Tool-Token: <token>
```

Create the ElevenLabs tool from local config with:

```powershell
python scripts\create_elevenlabs_call_context_tool.py
python scripts\create_elevenlabs_call_context_tool.py --apply
```

Attach it to **Gap Fill**. Configure the `twilio_call_sid` parameter from `{{twilio_call_sid}}` or ElevenLabs' system call SID if available. Stefanie must say a short stalling phrase before using it. If the tool returns `still_checking=true`, she should continue with the caller's own description.

## Post-call Artifacts

Each completed call writes both compatibility and demo-facing files:

```text
traces/<trace>/claim_note.md
traces/<trace>/FNOL_AutoLossNotice_<conversation-id>.md
traces/LATEST_CLAIM_NOTE.md
traces/LATEST_FNOL_AUTO_LOSS_NOTICE.md
traces/LATEST_CLAIM_STATE.json
traces/LATEST_TRACE_DIR.txt
```

For demos, open `traces/LATEST_FNOL_AUTO_LOSS_NOTICE.md`. It starts with a compact FNOL table, then the executive summary, validation checklist, policy match, loss details, and open items.

## Evaluation Loop

After a real call and post-call webhook have written the FNOL artifacts:

```powershell
python scripts\evaluate_latest_call.py
```

Defaults:

- latest trace from `traces\LATEST_TRACE_DIR.txt`
- `20` simulated jurors
- `gemini-2.5-pro`

Optional examples:

```powershell
python scripts\evaluate_latest_call.py --runs 5
python scripts\evaluate_latest_call.py --trace-dir traces\2026-04-26_08-32-27_elevenlabs-postcall_conv_5901kq47gstff1793ntd4r3gt67f
```

Outputs per trace:

- `jury_scores.json`
- `jury_scores.csv`
- `jury_summary.md`
- `latency_board.json`
- `latency_board.csv`

Latest shortcuts are also written under `traces\`, plus the append-only comparison file `traces\eval_runs.csv`.

## Audio Settings

For Register Twilio Calls, set both voice output and ASR input to `mu-law 8000 Hz`. ElevenLabs documents this as required for Twilio. Do not use the generic `PCM 16000 Hz` recommendation for this path.

Keep Scribe v2.2 Realtime and the German insurance ASR keywords. Background speech filtering is worth testing in noisy calls, but leave it off if it suppresses the caller.

## Fallback

If `register_call` fails or `USE_ELEVENLABS_REGISTER_CALL=0`, `/twilio/voice` falls back to the local Twilio Media Streams loop. That path is useful for debugging and sponsor-stack experiments, but it is no longer the demo-default runtime.
