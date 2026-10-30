---
name: research-spec
description: Transform a raw business question into a detailed investigation spec: classified shape, ranked falsifiable hypotheses, a source plan built from the sources actually enabled, and research threads with discriminating tests. Then scaffold a validated case and hand it to a native goal. Use before starting any research investigation in this repo.
argument-hint: "<business question>"
---

# Investigation Spec

Turn a raw question into a case workspace a native `/goal` can run. The output is a
**spec**, not an investigation: you design the case first, then run it.

**Question**: $ARGUMENTS

A 10/10 spec has four properties. Hold the work to them:

1. **Source-true**: every thread names an enabled source, with specific objects.
2. **Falsifiable**: every hypothesis has a discriminating test and a stated
   observation that would kill it.
3. **Decision-anchored**: the success criteria are specific, checkable, and tied
   to what the reader will *do* with the answer.
4. **Contract-clean**: `research validate` passes before you start researching.

## NEVER

- Leave a section heading with an empty or placeholder body.
- Design hypotheses or threads before discovering what data exists (Phase 2).
- Assume a source is available. Check `research source list`.
- Scaffold before the user confirms the spec (Phase 3 checkpoint).
- Guess metric definitions, table names, or tool names. Discover them live.
- Launch a Claude or Codex subprocess, invoke an Agent SDK, or write your own
  continuation loop. Native `/goal` owns execution.

## Phases

Read [references/method.md](references/method.md) before Phase 1. It holds each
phase in full. `uv run research contract method` prints the rules every case follows. Use [references/source-families.md](references/source-families.md)
in Phase 2 and [references/artifact-templates.md](references/artifact-templates.md)
in Phases 3 and 4.

1. **Frame.** Parse the question, classify its shape (`root-cause`, `comparison`,
   `exploration`), and map the causal system. Ask at most one clarifying question.
2. **Discover.** Enumerate the usable sources, orient across them live, and print a
   short orientation summary.
3. **Design.** Write ranked hypotheses, threads, and the remaining brief sections.
   Present the spec and **wait for confirmation or edits**.
4. **Scaffold.** Write the files to a tmpdir, run `research init --from-spec` (add
   `--rigour decision` when the answer drives a decision that matters), then
   fix and re-run `uv run research validate <case>` until it passes.
5. **Hand off.** Run `uv run research goal <case>`. If a native `/goal` is active,
   treat the contract as your instructions and continue in this session. Do not
   submit it as a nested slash command. If no goal is active, print the case summary
   and the exact `/goal` command, and stop.
