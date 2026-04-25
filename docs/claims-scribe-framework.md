# Claims Scribe Framework

Goal: sound like a human claims intake rep while producing a useful First Notice of Loss draft.

Socotra defines FNOL as a pre-claim process for capturing relevant data about a potential loss before the formal claim starts; it may be incomplete or revised, and can later become the basis for a claim. Source: [Socotra FNOL](https://docs.socotra.com/featureGuide/claims/fnol.html).

NAIC guidance for auto claims says safety comes first, collect driver/vehicle/insurance/witness/officer/time/date/location/weather/road details, and promptly call police for hit-and-run or theft. Source: [NAIC auto claim guidance](https://content.naic.org/article/what-you-should-know-about-filing-auto-claim).

Corti's ambient documentation workflow is a useful pattern: live transcript, fact extraction, then document generation after the interaction. Source: [Corti ambient RT](https://docs.corti.ai/workflows/ambient-rt).

## Scribe Loop

1. Listen to caller audio.
2. Append transcript fragments.
3. Extract facts into a mutable claim draft.
4. Ask only for the next missing high-value fact.
5. Confirm uncertain facts naturally.
6. At the end, read back a short human summary and explain next steps.

## Claim Draft Shape

```json
{
  "metadata": { "schema": "SAFETY_CALLER_POLICY_LOSS_PEOPLE_VEHICLES_POLICE_WITNESSES_COVERAGE_EVIDENCE_RESOLUTION_V1" },
  "Safety": { "summary": {}, "facts": [], "open_questions": [], "fields": {} },
  "Caller": { "summary": {}, "facts": [], "open_questions": [], "fields": {} },
  "Policy": { "summary": {}, "facts": [], "open_questions": [], "fields": {} },
  "Loss": { "summary": {}, "facts": [], "open_questions": [], "fields": {} },
  "People": { "summary": {}, "facts": [], "open_questions": [], "fields": {} },
  "Vehicles": { "summary": {}, "facts": [], "open_questions": [], "fields": {} },
  "Police": { "summary": {}, "facts": [], "open_questions": [], "fields": {} },
  "Witnesses": { "summary": {}, "facts": [], "open_questions": [], "fields": {} },
  "Coverage": { "summary": {}, "facts": [], "open_questions": [], "fields": {} },
  "Evidence": { "summary": {}, "facts": [], "open_questions": [], "fields": {} },
  "Resolution": { "summary": {}, "facts": [], "open_questions": [], "fields": {} }
}
```

Every field uses:

```json
{
  "value": null,
  "confidence": 0.0,
  "source_turn_ids": [],
  "needs_followup": true
}
```

## Slot Priority

Ask in this order unless the caller already gave the answer:

1. Safety: injuries, emergency services, immediate danger.
2. Identity: caller name, callback number, policy number.
3. Loss core: date, time, location, what happened.
4. Vehicles and people: insured vehicle, other vehicle, other driver info.
5. Police/witnesses/photos.
6. Drivability/towing/repair status.
7. Summary and next steps.

## Human Call Behavior

- Use short acknowledgements before data questions: "Okay", "Got it", "Right".
- Ask one question at a time.
- Do not over-explain internal process.
- If the caller gives several facts, summarize only the uncertain bits.
- For sensitive moments, slow down: injuries, panic, anger, unclear liability.
- Never say a claim is approved or coverage is confirmed; say the claim will be reviewed.

## Final Summary Template

```text
Okay, I have this as an auto loss on {date} around {time} at {location}.
You described {one_sentence_summary}. I noted {injury_status}, {police_status},
and {vehicle_status}. The next step is that a claims adjuster reviews this and
follows up at {callback}. Is that the best number?
```
