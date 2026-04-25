# Gemini Model Choice

Use a configurable primary/fallback pair for the claim-call brain: try `gemini-3-flash-preview` first, and fall back to `gemini-2.5-flash` if the preview model errors or is too slow.

Google describes Gemini 2.5 Flash as a price-performance model for low-latency, high-volume, thinking, and agentic use cases, with function calling, structured outputs, search grounding, URL context, and a 1,048,576-token input limit. Source: [Gemini API models](https://ai.google.dev/gemini-api/docs/models).

## Env Vars

```text
GOOGLE_API_KEY=
GEMINI_PRIMARY_MODEL=gemini-3-flash-preview
GEMINI_FALLBACK_MODEL=gemini-2.5-flash
```

## Why Flash

- Phone calls are latency-sensitive.
- Claim intake needs short conversational replies and structured outputs.
- The prompt and transcript can grow, but not beyond the 2.5 Flash context window in a demo.
- Quality matters more than absolute lowest cost because the hackathon goal is juror believability.

## Runtime Guidance

Use the model for:

- Dialogue policy: what to ask next, when to reassure, when to summarize.
- Structured claim state updates.
- Final concise claim summary.

Avoid using the model for:

- Audio buffering.
- Low-level interruption handling.
- Deterministic validation like phone/date/license plate formatting.

## Suggested Structured Output

```json
{
  "assistant_text": "Right, I have the date and location. Was anyone hurt?",
  "claim_patch": {
    "loss_date": "2026-04-25",
    "loss_location": "Berlin, ...",
    "injuries_reported": null
  },
  "next_slots": ["injuries_reported", "vehicles", "police_report"],
  "should_clear_audio": false,
  "handoff_required": false
}
```

Use `gemini-2.5-flash-lite` only if runtime latency or cost becomes the blocker. Google positions Flash-Lite as optimized for low latency. Source: [Vertex AI Gemini 2.5 Flash-Lite](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash-lite).
