# Lorem ipsum gate

In a decision case, a filler case and a reviewer named after a client both fail strict validation.

Source: src/agentic_research_loop/evidence.py, src/agentic_research_loop/validation.py
Inventory-id: validate

## Sub-features

- `filler`: lorem artifacts fail strict.
- `named`: a consistent manifest with reviewer `claude` fails strict.

## How to get to it (user POV)

- Run `research validate <case> --strict`.

## Driving it with verify

Preconditions: `H doctor` exits 0.

- **Drive.** Run `H drive lorem-gate`. It exits 0 and prints `lorem-gate: pass`.
- **Proof.** `lorem-gate.log` and a manifest block in the run directory.

## Gotchas

- A consistent manifest with a plausible reviewer id still passes. The gate cannot prove truth.
