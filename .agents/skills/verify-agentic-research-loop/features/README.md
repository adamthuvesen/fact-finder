# Feature map

## Baseline preconditions

`H launch` has run and `H doctor` exits 0. All state is under `.verify/state`.

## Driving conventions

Start each drive from baseline. With two or more drives, run `H reset` before each later drive.

## Inventory

`H inventory` prints the `research --help` subcommand list. Each subcommand is an `Inventory-id`.

Unmapped: `gsc`, `ga4` (need Google credentials and the network, so the offline drive cannot
reach them; `tests/test_google_api.py` covers them behind a mock).

## Proof, skip, and flake reporting

Each drive appends a manifest block. Report an unreachable feature with the command and the
unmet prerequisite. Never report one entry point as verified through another.

## Control

`H control` uses `lorem-gate`. It deliberately asserts that the lorem case exits 0, which must fail.

## Features

| Feature | File | Inventory ids | Last verified |
| --- | --- | --- | --- |
| case-lifecycle | [case-lifecycle.md](case-lifecycle.md) | init, goal, validate, review-snapshot, list | 7be7160-dirty 2026-11-04 created |
| quick-answer | [quick-answer.md](quick-answer.md) | init, validate | 7be7160-dirty 2026-11-04 created |
| lorem-gate | [lorem-gate.md](lorem-gate.md) | validate | 7be7160-dirty 2026-11-04 created |
| sql-gate | [sql-gate.md](sql-gate.md) | validate | 7be7160-dirty 2026-11-04 created |
| sources | [sources.md](sources.md) | source, doctor | 7be7160-dirty 2026-11-04 created |
| consumer-setup | [consumer-setup.md](consumer-setup.md) | setup, source | 7be7160-dirty 2026-11-04 created |
