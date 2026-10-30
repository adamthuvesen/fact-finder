---
name: research-spec
description: Transform a raw business question into a detailed investigation spec: classified shape, ranked falsifiable hypotheses, a source plan built from the sources actually enabled, and research threads with discriminating tests. Then scaffold a validated case and hand it to a native goal. Use before starting any research investigation in this repo.
argument-hint: "<business question>"
---

# Investigation Spec

Turn a raw question into a case a native `/goal` can run. You design the case first, then run it.

**Question**: $ARGUMENTS

A good spec is:

1. **Source-true**: every thread names an enabled source, with specific objects.
2. **Falsifiable**: every hypothesis has a discriminating test and an observation that kills it.
3. **Decision-anchored**: success criteria are checkable and tied to what the reader will do.

## NEVER

- Design hypotheses or threads before discovering what data exists.
- Assume a source is available. Check `uv run research source list`.
- Scaffold before the user confirms the spec.
- Guess metric definitions, table names, or tool names. Discover them live.
- Launch a Claude or Codex subprocess, invoke an Agent SDK, or write your own continuation loop.

## Phases

Read [references/method.md](references/method.md) before you start. It holds the judgement for
each phase.

1. **Frame.** Classify the shape and map the causal system. Ask at most one clarifying question.
2. **Discover.** Orient across the usable sources live, and print a short summary.
3. **Design.** Write ranked hypotheses and threads. Present them and **wait for edits**.
4. **Scaffold.** Run `uv run research init <slug> --template <shape> --question "<question>"`,
   and write the design into the files it creates. `uv run research validate <case>` names every
   gap with its fix.
5. **Hand off.** Run `uv run research goal <case>`. If a native `/goal` is active, follow that
   contract in this session. Do not submit it as a nested slash command. If no goal is active,
   print the `/goal` command and stop.
