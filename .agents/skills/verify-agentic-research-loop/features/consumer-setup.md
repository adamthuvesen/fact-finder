# Consumer setup

A repo that only pins the wheel gets skills and bundles with one command.

Source: src/agentic_research_loop/repo_setup.py
Inventory-id: setup, source

## Sub-features

- `links`: both skills resolve through relative links from the installed wheel.
- `bundles`: `source list` shows packaged bundles in a repo with no `examples/`.

## How to get to it (user POV)

- Run `research setup` in a repo with a `[tool.agentic-research-loop]` table.

## Driving it with verify

Preconditions: `H doctor` exits 0.

- **Drive.** Run `H drive consumer-setup`. It exits 0 and prints `consumer-setup: pass`.
- **Proof.** `consumer-setup.log` and a manifest block in the run directory.

## Gotchas

- The links point into the consumer's environment, so run setup again after recreating it.
