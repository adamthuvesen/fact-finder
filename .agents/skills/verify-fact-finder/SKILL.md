---
name: verify-fact-finder
description: Drives the fact-finder `research` CLI, installed from a wheel, in throwaway consumer repos. Use to run, launch, drive, or verify fact-finder, or to prove a change to it works.
---

# Verify fact-finder

The helper builds a wheel from this checkout, installs it into a fresh venv, and drives the
installed `research` CLI. Each drive gets its own temp HOME and consumer repo. Nothing touches the
network, a model, or your real HOME.

## Run

From the repo root:

- `make verify` after a change. It runs the drives whose paths changed against `main`, plus
  uncommitted and untracked files. With no match, it runs the smoke drive.
- `make verify ARGS=all` before you hand over larger work. It takes under 10 seconds.
- `make verify ARGS="sources sql-gate"` runs the named drives.
- `make verify ARGS=list` prints each drive, what it proves, and the paths it covers.
- `make verify ARGS=control` re-drives the lorem case against a wrong expectation. It exits 0
  only when it observes FAIL.

## Reading results

Each drive prints `PASS|FAIL <drive> <seconds>s <detail>`. A FAIL detail names the command, the
expected exit code or text, and what happened. The run exits non-zero when any drive fails.

Evidence goes to `.verify/runs/<utc>-<sha7>[-dirty]/`: one `<drive>.log` with every command, exit
code, and output, `preflight.json` with the wheel and the child environment, and `summary.json`.
There is no retry, so there is no FLAKY result. A failure is a FAIL.

A `tripwire` FAIL means the CLI tried to run a stubbed tool (`claude`, `codex`, `curl`, `brew`,
`launchctl`, and others). Read the logged command, and treat it as a boundary break.
A `repo-state` FAIL means a run changed this checkout: a file, the index, HEAD, an ignored
path, or `.git/config`. Drives must touch only their scratch copies.

## Limits

- `gsc` and `ga4` need Google credentials and the network. `tests/test_google_api.py` covers them
  behind a mock. To prove them for real, run them by hand with read-only ADC.
- `doctor` reads config only. No drive proves that a live MCP server or connector answers.
- The edit hook is proved installed, not fired by a live agent client.
- A consistent case with a plausible reviewer id passes. The gate cannot prove that a claim is true.

## Gotchas

- The drives run in parallel, one consumer each. A new drive must not share files between
  sessions.
- `uv build` runs with your real uv cache. Only the CLI runs in the isolated environment.
- Write a filled case through `research review-snapshot`, as `drives.py::fill` does. A
  hand-written `review.json` hash goes stale at the first edit.
