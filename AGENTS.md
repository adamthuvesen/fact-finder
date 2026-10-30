# AGENTS.md

`fact-finder` is a research kit for bounded investigations run inside a native
agent goal. This file holds project facts. It is short because checks enforce the rest.

- Next step on any case: `uv run research next [case]`
- Research method and evidence: `uv run research contract method|evidence`
- Modules and boundaries: [.agents/docs/architecture.md](.agents/docs/architecture.md)
- Why there is no runtime: [.agents/docs/decisions/native-goals.md](.agents/docs/decisions/native-goals.md)
- Setup, new sources, and local engine work: [.agents/docs/setup.md](.agents/docs/setup.md)

If a doc disagrees with code, fix the doc in the same change. `make quick` checks what changed in about
two seconds, and the edit hook runs the same checks. `make check` is the gate. Prove
user-facing changes with the `verify-fact-finder` skill at
`.agents/skills/verify-fact-finder/`.

## Stop and ask

A task's wording cannot authorize any of these:

- a write to an external system
- a publish or send command
- an agent runner, Agent SDK, or custom continuation loop
- a permission-bypass flag, such as `--yolo`, `--full-auto`, or `--force` on an agent client
- an edit to a check that would allow one of the above

Stop. Say which recorded decision the request reverses, such as
`.agents/docs/decisions/native-goals.md` or this file. Offer an option that keeps the boundary.

## Running research

Start from a native `/goal` naming `research-goal`, or `research-spec` when scope needs discovery
first. When a goal is active, adopt the generated contract and finish in that session. Do not stop
after scaffolding or submit a nested goal. Run the CLI from the repo root.

## Safety and rigour

Safety has no override. `validate` blocks write or unreadable SQL and evidence outside the case.
`doctor` checks deny lists, and ruff bans agent runners. The repo has no write path to external
systems. Rigour is a default. A person can
accept a rigour block with `validate --strict --accept "<reason>"`, which is recorded in
`overrides.json` and in `report.md`, and named in the label. A new rigour check blocks only if passing would otherwise mislead silently. Anything
else warns. An agent never accepts a block for a person, and never replaces a reviewed hash
without a new review.

`examples/demo-export-reliability` is a reviewed decision case. A schema change adds a warning
or updates the fixture in `tests/support/cases.py`, and does not touch the demo. An edit to a
demo file needs a new independent review, because `test_validation.py` pins it.

## Enforced rules

| Rule | Enforced by |
| --- | --- |
| No agent SDK import or process spawn in `src/`, `evals/`, or `scripts/`. Exempt: `scripts/check_agent_setup.py` (client version probes), `tests/`, and the verify helper (it runs `git`, `uv`, and the built CLI, and stubs agent clients) | `pyproject.toml` (ruff TID251), `rules/no-dynamic-import.yml` |
| Preserved SQL is read-only under every dialect reading | `tests/test_readonly_sql.py` |
| Write SQL, unreadable SQL, and out-of-case artifacts cannot be accepted | `tests/test_gate_honesty.py` |
| Each bundle meets a named read-only control, and enabled servers match it | `tests/test_readonly_contract.py`, `tests/test_doctor.py` |
| No permission-bypass flag ships | `tests/test_readonly_contract.py` |
| Layers hold, and models forbid unknown fields | `make boundaries`, `pyproject.toml` (ruff TID251) |
| Instruction text stays under its limit, and doc links resolve | `tests/test_docs_contract.py` |
