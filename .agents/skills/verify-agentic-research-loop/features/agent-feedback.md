# Agent feedback

A new source, the next step, and a bad edit each give one concrete fix.

Source: src/agentic_research_loop/next_step.py, src/agentic_research_loop/lint.py, src/agentic_research_loop/agent_hooks.py
Inventory-id: next, lint, hook, source

## Sub-features

- `scaffold`: `source new` loads, and `enable` refuses it until each `TODO` is replaced.
- `next`: names init, then the goal, then a safety finding first.
- `hooks`: `setup` installs the client hooks from the wheel.

## How to get to it (user POV)

- Run `research source new`, `research next`, `research lint`, and `research setup`.

## Driving it with verify

Preconditions: `H doctor` exits 0.

- **Drive.** Run `H drive agent-feedback`. It exits 0 and prints `agent-feedback: pass`.
- **Proof.** `agent-feedback.log` and a manifest block in the run directory.

## Gotchas

- This proves the hook is installed. It does not run a live client.
