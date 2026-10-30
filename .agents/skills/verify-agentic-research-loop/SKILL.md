---
name: verify-agentic-research-loop
description: Drives the agentic-research-loop `research` CLI, installed from a wheel, in a throwaway consumer repo. Use to run, launch, drive, or verify agentic-research-loop, or to prove a change to it works.
---

# Verify agentic-research-loop

Helper: `.agents/skills/verify-agentic-research-loop/verify` (`H` below), from the repo root.

## Launch / Reset

`H launch` builds a wheel, installs it in a fresh venv, and creates a consumer repo. Ready
signal: `ready: ... installed from a wheel`. `H reset` returns the consumer to baseline.

## Doctor

`H doctor` exits non-zero when the checkout fingerprint changed since launch, the target is
outside `.verify/state`, the CLI is missing, or the tripwire fired.

## Drive

Session: `H launch`, `H doctor`, one or more `H drive <feature>`, `H control` once, `H clean`.
With two or more drives, run `H reset` before each later drive. `H control` needs no reset.
Each drive and `H clean` print the run directory, so use the path they print. Features are in [features/README.md](features/README.md). A failed
drive is FAIL. One retry after doctor and reset is recorded `flaky`.

## Evidence

`.verify/runs/<utc>-<sha7>[-dirty]/` holds `<feature>.log` (each command, exit code, output)
and `manifest.txt`. No drive reads a secret, so there is nothing to redact.

- **Control:** `H control` re-drives the lorem case with a deliberately wrong expectation: exit 0
  and the pass message. The helper's assertion must fail, so the right output is
  `control: fail-observed`. `passed-unexpectedly` means the harness cannot fail.

## Cleanup

`H clean` writes the tripwire state to the run directory, removes `.verify/state`, and keeps
`.verify/runs`. A fired tripwire exits non-zero: stop and report what ran.

## Helper

- `H launch`, `H doctor`, `H reset`, `H control`, `H clean`: as above.
- `H drive <feature>`: run one feature.
- `H inventory`: print the command list, from `research --help`.
- `H exec -- research <args>`: run a command in the isolated environment, for diagnosis.
- `VERIFY_TARGET=<path>`: exists only to prove that doctor and drive refuse another target.
