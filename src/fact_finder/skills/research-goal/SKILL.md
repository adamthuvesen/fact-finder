---
name: research-goal
description: Run a bounded research case inside an active Claude Code or Codex native /goal, or prepare the launch command when no goal is active. Use for starting, continuing, or completing a reproducible investigation without a repository agent runtime.
---

# Research Goal

Work from the repository root. `uv run research next [case]` says what to do at any point,
with the exact command. `uv run research --help` lists the flags.

- **A native `/goal` is active:** scaffold if needed, then complete the investigation in this
  session. Treat `uv run research goal <case>` as your instructions. Do not submit it as a
  nested slash command, return it to the user, or stop after scaffolding.
- **No goal is active:** scaffold if needed, return the case path and the `/goal` command, and
  stop. A case run without a goal has no persistence: the work dies with the turn.

Scaffold with `uv run research init <slug> --question "<specific question>"`. Add
`--rigour decision` when the answer drives a decision that matters. Do not ask for confirmation
when the question is already bounded.

Never launch a Claude or Codex subprocess, invoke an Agent SDK, or add a custom continuation
loop. Native `/goal` owns persistence, continuation, pause, and resume.
