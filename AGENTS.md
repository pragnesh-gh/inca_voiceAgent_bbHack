# Inca Voice Agent — Project Instructions

You (the coding agent) are working on a 24-hour solo hackathon project. Read this file at the start of every session.

## Project goal

Build a phone-based voice agent for the Inca track at Big Berlin Hack. The agent handles inbound insurance claim calls. The win condition is binary: more than 50% of human jurors must vote "human" after calling the agent.

The current state is a working pipeline (LiveKit + Gradium STT/TTS + Gemini 2.5 Flash + ai-coustics). It needs to be made (a) more human-sounding, (b) capable of handling the full claim intake, and (c) impressive on demo day.

## Hard rules

1. **No TDD.** This is a 24-hour hackathon. Do NOT write tests first. Do NOT set up testing infrastructure. Validate by running the agent and using the eval/score.py adversarial detector.
2. **Single agent, solo developer.** The user is alone. You are not running parallel subagents. Do not invoke `dispatching-parallel-agents`. One task at a time, stop and report.
3. **Stop at every checkpoint.** After each task in the current plan, report back with what you did and wait. Don't auto-chain into the next task.
4. **Don't refactor.** No reorganizing, renaming, or "improving" code that isn't part of the current task. The user has very limited time.
5. **Ask if uncertain.** Better to pause than to invent behavior.

## Tech stack (locked, do not substitute)

- Python 3.11
- LiveKit Agents 1.5+ with `[google,silero]` extras
- `livekit-plugins-gradium` for STT and TTS
- `livekit-plugins-ai-coustics` for noise cancellation
- Gemini 2.5 Flash via the `google` plugin
- Tavily (`tavily-python`) for external lookup tool
- python-dotenv for env loading

API keys are already in .env. Do not regenerate or rewrite .env.

## Repo layout

```
.
├── AGENTS.md               # this file (CLAUDE.md is a symlink)
├── README.md               # for submission — keep updated
├── agent.py                # the main entry point — already runs
├── prompts/
│   ├── system.md           # base system prompt — iterate heavily
│   ├── fewshot.md          # real call transcript examples
│   └── stalling.md         # phrases for tool-call gaps
├── tools/                  # function-calling tools the agent can use
│   ├── policy.py
│   ├── claim.py
│   └── search.py           # Tavily wrapper
├── eval/
│   ├── detector_prompt.md  # AI-tells detector prompt
│   └── score.py            # runs detector on a transcript
├── data/
│   └── ambience.mp3        # call-center background loop
├── transcripts/            # saved calls (one JSON per call)
└── requirements.txt
```

## Workflow

The user iterates by:
1. Running the agent, having a call (via LiveKit playground or phone)
2. Saving the transcript to `transcripts/`
3. Running `eval/score.py` to get an AI-detection score
4. Asking you to fix specific tells the detector flagged

Your job most often is: edit `prompts/system.md` or `prompts/fewshot.md` to defeat specific tells.

## Communication style

- Terse. No filler. No "Great question!"
- Lead with what you did. Then what's open.
- If blocked, say so in one sentence.

## Superpowers skills — what applies

- `brainstorming` — SKIP. The architecture is already decided.
- `writing-plans` — only when explicitly asked.
- `using-git-worktrees` — SKIP for this project. The user works in a single directory.
- `subagent-driven-development` — SKIP. Single agent only.
- `dispatching-parallel-agents` — SKIP.
- `test-driven-development` — DISABLED. See rule 1.
- `verification-before-completion` — yes. "Verified" means "I ran the agent and confirmed expected behavior," not "I wrote tests."
