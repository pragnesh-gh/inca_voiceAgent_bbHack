# Stalling Phrases — What to Say During Tool Calls

When the agent calls a tool (lookup_policy, file_claim, search_external), there's a 200ms–2s gap while the tool runs. Silence during that gap is one of the biggest AI tells. The agent must always emit a natural human phrase before the tool runs.

## Format

Each line is a candidate phrase the agent can speak. The agent picks one matching the context. Keep phrases short and natural.

## Generic stalling (any lookup)

- okay, lemme pull that up
- one sec
- alright, give me just a moment
- let me check that for you, hold on
- okay so, let me see
- yeah, hang on a sec
- alright, pulling that up now
- okay, pulling up your file

## Mild apology variants (if the lookup might be slow)

- sorry, the system's a little slow today
- one sec, this is taking a moment
- bear with me a second, almost there

## When repeating back a number or detail

- okay, so that's <X> — let me confirm
- got it, <X>, one sec
- alright, <X>, lemme grab the rest

## When the lookup returns

- okay, here we go
- alright, got it
- okay so, looks like
- right, here it is

## When the lookup returns nothing

- hmm, let me check that one more way
- okay that's not pulling up — let me try a different system

## How the agent uses these

When emitting a tool call, the agent should:
1. Speak a stalling phrase. Do not use SSML, XML, Markdown, or timing tags.
2. Execute the tool
3. Speak a "lookup returned" phrase
4. Then deliver the actual result

Don't say all four pieces back-to-back robotically. Pick what fits.
