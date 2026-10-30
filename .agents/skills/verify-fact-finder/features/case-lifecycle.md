# Case lifecycle

A case moves from scaffold to a strict pass, and a late edit makes its review stale.

Source: src/fact_finder/cli.py, src/fact_finder/research.py
Inventory-id: init, goal, validate, review-snapshot, list

## Sub-features

- `scaffold`: init, then goal prints an absolute path.
- `strict`: a decision case fails strict on the scaffold and passes when filled.
- `stale`: a report edit warns; `--pinned` fails; `--json` reports it; list shows the stale review.

## How to get to it (user POV)

- Run `research init`, `goal`, `validate [--strict] [--json]`, `review-snapshot`, `list`.

## Driving it with verify

Preconditions: `H doctor` exits 0.

- **Drive.** Run `H drive case-lifecycle`. It exits 0 and prints `case-lifecycle: pass`.
- **Proof.** `case-lifecycle.log` and a manifest block in the run directory.

## Gotchas

- The drive writes the filled artifacts itself. It builds `review.json` from `research review-snapshot`.
