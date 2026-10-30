# Quick answer

A person gets a labelled exploratory answer with very little ceremony. Write SQL still fails, and no flag overrides it.

Source: src/fact_finder/validation.py
Inventory-id: init, validate

## Sub-features

- `quick-pass`: init, one edit to `report.md`, then strict validation passes with its label.
- `safety`: write SQL fails with `--accept`, and nothing is recorded.

## How to get to it (user POV)

- Run `research init <slug>`, write the answer in `report.md`, then run `research validate <slug> --strict`.

## Driving it with verify

Preconditions: `H doctor` exits 0.

- **Drive.** Run `H drive quick-answer`. It exits 0 and prints `quick-answer: pass`.
- **Proof.** `quick-answer.log` and a manifest block in the run directory.

## Gotchas

- A warning does not fail the command. Read the output for what would make the answer stronger.
