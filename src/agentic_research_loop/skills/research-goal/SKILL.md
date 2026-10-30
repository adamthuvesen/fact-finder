---
name: research-goal
description: Run a bounded research case inside an active Claude Code or Codex native /goal, or prepare the launch command when no goal is active. Use for starting, continuing, or completing a reproducible investigation without a repository agent runtime.
---

# Research Goal

The `research` CLI is internal plumbing. Execution stays inside the current session.

## Choose the mode first

- **A native `/goal` is active:** execution mode. Scaffold if needed, then complete
  the investigation in this session.
- **No native goal is active:** preparation mode. Scaffold if needed, then return the
  generated `/goal` command for the user to submit. Do not begin the investigation.
  A case run without a goal has no persistence: the work dies with the turn.

## Prepare the case

1. Work from the repository root.
2. Resolve an existing case with `uv run research goal <case>`, or scaffold one with
   `uv run research init <slug> --question "<specific question>" --template <exploration|root-cause|comparison>`.
   Add `--rigour decision` when the answer drives a decision that matters. The default is a
   labelled exploratory answer with no evidence manifest or review. Narrow sources with `--sources a,b`, focus one with `--source-hint a=TEXT`, attach
   local files with `--context-path PATH`, or use `--local-only`. Check what is wired
   with `uv run research source list`.
3. Read `brief.md`. Resolve placeholders that would materially change the answer. Do
   not ask for confirmation when the question is already bounded.
4. Run `uv run research validate <case>` and fix structural failures.
5. Run `uv run research goal <case>` to get the contract with the absolute case path.

## Execution mode

Run `uv run research contract method` and follow it. For a decision case, also follow
`uv run research contract evidence`. Treat the generated contract as the operating instructions for the active goal. Do
not submit it as a nested slash command, return it to the user, or stop after
scaffolding. Continue immediately with the research, and finish with the validation
result and conclusion in your final response.

## Preparation mode

Return the case path and the exact generated `/goal` command in a code block.

---

Never launch a Claude or Codex subprocess, invoke an Agent SDK, or add a custom
continuation loop. Native `/goal` owns persistence, continuation, pause, and resume.
