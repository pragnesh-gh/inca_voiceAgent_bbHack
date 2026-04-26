# Submission Manual

This file is for judges and organizers who want to test the INCA Human Test demo.

## Live Availability Note

The phone agent is live through a local webhook server exposed with a stable ngrok HTTPS tunnel. I used this setup because the project needs local server tools for policy lookup, post-call FNOL documentation, and live context lookups, and this was the most reliable way to keep that toolchain working during the hackathon.

During judging, I will keep the laptop, `agent.py`, and ngrok tunnel running. If the number rings but the call does not connect, or if you see a Twilio/ElevenLabs application error, please message:

```text
Pragnesh Kumar Pallaprolu
Discord: ppk2086
```

The demo number can be called from any normal phone number. It is not limited to my own test phone.

## Quick Test

Video demo:

```text
https://www.loom.com/share/8752e4483ce640b79e18c02bed5cebfa
```

Call:

```text
+49 30 75679047
```

Agent:

```text
Stefanie Kühne, Meridian Mutual auto claims
```

Best first test prompt:

```text
Hi, I need to report an accident with my car.
```

The agent should answer like an auto claims adjuster, check safety if needed, let you tell the story, then gather missing FNOL details.

## Supported Languages

- English
- German
- Mixed English/German

German insurance vocabulary Stefanie should understand:

```text
Kasko, Vollkasko, Teilkasko, Haftpflicht, SF-Klasse, Selbstbeteiligung,
Werkstattbindung, Schutzbrief, Polizei-Vorgangsnummer, Wildunfall,
Auffahrunfall, Parkschaden, Glasbruch, Fahrerflucht
```

## Things To Try On The Call

Calm English:

```text
I rear-ended someone near Alexanderplatz about half an hour ago. Nobody is hurt, but my front light is broken.
```

German:

```text
Ich hatte einen Auffahrunfall in Berlin. Niemand ist verletzt, aber die Polizei war da.
```

Mixed:

```text
I think it may be Vollkasko, but I'm not sure about the Selbstbeteiligung.
```

Safety triage:

```text
I'm still on the side of the road and my passenger may be hurt.
```

Policy lookup demo:

```text
My name is Pragnesh Kumar Pallaprolu. My date of birth is 26 October 2001.
```

Stefanie should not sound like a checklist. She should ask short questions, use light backchannels, and avoid repeatedly summarizing every answer.

## Guardrails

The ElevenLabs agent has ten claims-specific guardrails configured. They are part of the demo, not just generic moderation.

Streaming guardrails that end the call immediately:

- No internal flag disclosure: avoids exposing fraud flags, SIU referrals, or other internal risk markers.
- No persona break: avoids bot/self-disclosure language that would immediately break the human test.

Post-response guardrails that block and replace the risky reply:

- No fault attribution: regenerate neutrally and document facts only.
- No bank or IBAN solicitation: regenerate without asking for banking details.
- No repair authorization on call: regenerate with written-confirmation language.
- No premium, renewal, or cancellation talk: redirect to follow-up by the policy team.
- No third-party PII echo: do not read unrelated third-party PII aloud.
- No invented identifiers: do not fabricate claim numbers, policy numbers, case numbers, or internal IDs.
- No sycophantic agreement: validate emotion, not coverage or liability.
- No medical or treatment advice: redirect to medical care or emergency services.

If a streaming guardrail intentionally ends a stress-test call, that is expected behavior and not a telephony failure. If a post-response guardrail triggers, ElevenLabs blocks the unsafe draft and retries with corrective guidance so Stefanie stays in role and avoids legally or operationally risky answers.

## What The Agent Should Collect

Core FNOL facts:

- Caller identity or policy lookup details
- Date and time of loss
- Location of loss
- Loss type
- Safety status and injuries
- Vehicle status and whether it is drivable
- Current vehicle location
- Other party details if relevant
- Police involvement and case number if available
- Damage description
- Callback/contact details
- Evidence such as photos or witnesses if natural

## Documentation Output

After the call ends, wait roughly 10-60 seconds for post-call processing.

Open:

```text
traces/LATEST_FNOL_AUTO_LOSS_NOTICE_REDACTED.pdf
```

This is the judge-facing branded redacted PDF. It should contain:

- FNOL summary table
- Executive summary
- Validation checklist / missing essentials
- Safety, caller, loss, people, vehicle, police, evidence, and resolution sections
- Key moment timeline

Raw/debug files:

```text
traces/LATEST_FNOL_AUTO_LOSS_NOTICE.md
traces/LATEST_CLAIM_STATE.json
traces/LATEST_TRACE_DIR.txt
```

## Optional Dashboard / Logs

If running locally, useful views are:

- ElevenLabs Conversations dashboard: call audio, transcript, metadata
- ngrok inspector: `http://127.0.0.1:4040`
- Local trace folder from `traces/LATEST_TRACE_DIR.txt`

## Runtime Setup For Local Reproduction

Use Python 3.11 in the `inca_bb_hack` conda environment:

```powershell
conda activate inca_bb_hack
python -m pip install -r requirements.txt
python agent.py
```

Expose the local server:

```powershell
ngrok http 8088 --domain <stable-ngrok-domain>
```

If Twilio needs rebinding:

```powershell
python scripts\configure_twilio_media_streams.py --public-url https://<stable-ngrok-domain> --apply
```

Before running that command, verify:

```text
TWILIO_PHONE_NUMBER=+493075679047
```

The hackathon Twilio account is shared. Do not update any other team's number.

## Tech Stack

Primary live call path:

- Twilio Programmable Voice
- ElevenLabs Conversational AI / Register Twilio Calls
- Google Gemini post-call scribe and evaluator
- Tavily narrow context lookup tool

Supporting/fallback path:

- Gradium STT/TTS
- ai-coustics
- Pipecat

## Expected Behavior

A successful run means:

1. The phone call connects and Stefanie answers.
2. Stefanie handles interruptions and pauses naturally.
3. The call can be conducted in English, German, or mixed language.
4. A structured FNOL note is produced after the call.
5. The redacted PDF is suitable to show judges without exposing raw PII.
