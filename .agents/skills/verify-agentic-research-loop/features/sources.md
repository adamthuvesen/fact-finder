# Source bundles

Enabling a bundle generates each client config and deny list, and doctor checks them.

Source: src/agentic_research_loop/source_bundles.py, src/agentic_research_loop/doctor.py
Inventory-id: source, doctor

## Sub-features

- `enable`: github and stripe wire, with deny lists.
- `doctor`: passes, then fails on a tampered config.
- `bad-json`: `source disable` gives a clean error, then works after repair.

## How to get to it (user POV)

- Run `research source enable|disable` and `research doctor`.

## Driving it with verify

Preconditions: `H doctor` exits 0.

- **Drive.** Run `H drive sources`. It exits 0 and prints `sources: pass`.
- **Proof.** `sources.log` and a manifest block in the run directory.

## Gotchas

- Doctor reads config. It never contacts a server.
