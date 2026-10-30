# AGENTS.md

`agentic-research-loop` is a research kit for bounded investigations run inside a native
agent goal. This file holds project facts. It is short because checks enforce the rest.

- Operating model: [program.md](program.md)
- Research method: [method.md](src/agentic_research_loop/contract/method.md)
- Evidence and review: [docs/evidence-contract.md](docs/evidence-contract.md)
- Modules and boundaries: [.agents/docs/architecture.md](.agents/docs/architecture.md)
- Why there is no runtime: [.agents/docs/decisions/native-goals.md](.agents/docs/decisions/native-goals.md)
- Setup and new sources: [.agents/docs/setup.md](.agents/docs/setup.md)

If a doc disagrees with code, fix the doc in the same change. `make check` is the gate. Prove
user-facing changes with the `verify-agentic-research-loop` skill at
`.agents/skills/verify-agentic-research-loop/`.

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
first. New cases are exploratory: a labelled quick answer. Use `--rigour decision` when the answer
drives a decision that matters. When a goal is active, adopt the generated contract and finish in that session. Do not
stop after scaffolding or submit a nested goal. Run the CLI from the repo root. The rules for a
case live in one place, `uv run research contract method`.

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

| Rule | Enforced by | Added |
| --- | --- | --- |
| No agent SDK import or process spawn in `src/`, `evals/`, or `scripts/`. Exempt: `scripts/check_agent_setup.py` (client version probes), `tests/`, and the verify helper (it runs `git`, `uv`, and the built CLI, and stubs agent clients) | `pyproject.toml` (ruff TID251), `rules/no-dynamic-import.yml` | 2026-11-04 |
| Pydantic models subclass `StrictModel`, which forbids extra fields | `pyproject.toml` (ruff TID251), `rules/strict-model-only.yml` | 2026-11-04 |
| cli above domain above I/O; nothing imports cli | `make boundaries` | 2026-11-04 |
| Preserved SQL is read-only under every dialect reading | `tests/test_readonly_sql.py` | 2026-11-04 |
| Decision cases: claims cite declared sources, arithmetic holds, and a named review exists | `tests/test_evidence.py` | 2026-11-04 |
| An exploratory report needs its label, or an accepted gap shown in the report. Write SQL, unreadable SQL, and out-of-case artifacts cannot be accepted | `tests/test_validation.py`, `tests/test_gate_honesty.py` | 2026-11-04 |
| A decision case filled with lorem ipsum or reviewer `claude` fails strict | `tests/test_end_to_end.py` | 2026-11-04 |
| Each bundle meets a named read-only control from a closed set | `tests/test_readonly_contract.py` | 2026-11-04 |
| Enabled servers match their bundle definition and control, apart from declared user-filled values | `tests/test_doctor.py` | 2026-11-04 |
| `.mcp.json` ships neutral | `tests/test_mcp_configs_consistent.py` | 2026-11-04 |
| Source lists are generated, never hand-edited | `tests/test_source_catalog.py` | 2026-11-04 |
| No permission-bypass flag ships | `tests/test_readonly_contract.py` | 2026-11-04 |
| Goal contract paths are absolute | `tests/test_cli.py` | 2026-11-04 |
| Instruction lines stay under 500; relative doc links resolve; skills keep their hard limits | `tests/test_docs_contract.py` | 2026-11-04 |
