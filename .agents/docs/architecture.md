# Architecture

`fact-finder` is a research kit, not an agent runtime. The client owns execution. The repo
owns everything around it.

`pyproject.toml` lists the module layers, and `make boundaries` enforces them. Skills, bundles, hooks,
and the contract are package data, so a consumer gets them from its pin. Consumer code imports only
`fact_finder.api`.

## Source boundary

A bundle is one `<name>.toml`. `client_configs` generates each client's shape and deny list from its
server. It adds only what is missing and keeps every existing value. A server name it did not add is a
collision: the command fails and changes nothing. `config/sources.json` says which sources a repo
wants. The local `.research/wiring.json` records what research added. `reconcile_clients` is the one
path that brings client files in line with both.

`read_only_control` names one mechanism from a closed set. `research doctor` fails when `url_suffix`,
`server_flag`, `arg_absent`, or `statement_allowlist` does not hold. It reports `credential_scope`,
`credential`, and `native` as declared, because they live in a grant no file can show. Doctor never
contacts a server, so a pass says nothing about what the upstream server does.

## SQL boundary

`readonly_sql` parses preserved SQL under eight dialect readings and requires every reading that parses
to be read-only. It cannot detect `SELECT side_effect_proc()`. The read-only role on the connection is
the real guard.

## Validation

Each finding has a kind, and `validation.assess_case` decides what blocks. `evidence_findings` reads
the evidence contract through `evidence_files`, which loads `evidence_models`. `acceptance` records a
person's override in `overrides.json`. `feedback.problem` renders every message in one format.

## Deliberate omissions

The repo has no subprocess runners, cycle markers, retry loop, progress hash, stall detector, machine
challenge state, permission bypass flags, status renderer, or publishing layer. See
[the decision record](decisions/native-goals.md) and [the canary](../../evals/native-goal/README.md).
