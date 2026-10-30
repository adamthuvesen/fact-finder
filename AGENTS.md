# AGENTS.md

`fact-finder` is a research kit for bounded investigations run inside a native
agent goal. This file holds project facts. It is short because checks enforce the rest.

- Next step on any case: `uv run research next [case]`
- Research method and evidence: `uv run research contract method|evidence`
- Modules and boundaries: [.agents/docs/architecture.md](.agents/docs/architecture.md)
- Why there is no runtime: [.agents/docs/decisions/native-goals.md](.agents/docs/decisions/native-goals.md)
- Setup, new sources, and local engine work: [.agents/docs/setup.md](.agents/docs/setup.md)

If a doc disagrees with code, fix the doc in the same change. Run `make quick` after each edit: it checks
changed files and local cases under `research/`, and the edit hook runs it. Run `make check` before
you commit: it is the whole gate, in about 15 seconds, and the first CI step. `make fix` applies the
auto-fixers (ruff lint and format). Prove
changes with `make verify` (`verify-fact-finder` skill at `.agents/skills/verify-fact-finder/`).

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

Safety has no override, and the checks below enforce it. Rigour is a default. A person can
accept a rigour block with `validate --strict --accept "<reason>"`, which is recorded in
`overrides.json` and in `report.md`, and named in the label. A new rigour check blocks only if
passing would otherwise mislead silently. Anything else warns. An agent never accepts a block for a person, and never replaces a reviewed hash
without a new review.

`examples/demo-export-reliability` is a reviewed decision case. A schema change adds a warning
or updates the fixture in `tests/support/cases.py`, and does not touch the demo. An edit to a
demo file needs a new independent review, because `test_validation.py` pins it.

## Enforced Rules

Each "Enforced by" cell cites `path::name` (a function or class the file defines) or a `make` target.
`tests/test_docs_contract.py::test_enforced_rules_cite_real_checks` fails on anything else.

| Rule | Enforced by | Added |
| --- | --- | --- |
| No agent SDK import or process spawn in `src/`, `evals/`, or `scripts/`. Exempt: `scripts/check_agent_setup.py` (client version probes), `tests/`, and the verify helper (it runs `git`, `uv`, and the built CLI, and stubs agent clients) | `make lint` (ruff TID251), `make rules` | 2026-11-04 |
| Preserved SQL is read-only under every dialect reading | `tests/test_readonly_sql.py::test_rejected`, `tests/test_readonly_sql.py::test_writes_the_parser_reads_as_reads_are_rejected` | 2026-11-04 |
| Write SQL, unreadable SQL, and out-of-case artifacts cannot be accepted | `tests/test_validation.py::test_write_sql_blocks_and_cannot_be_accepted`, `tests/test_gate_honesty.py::test_unreadable_queries_fail_closed`, `tests/test_validation.py::test_artifact_outside_the_case_blocks_and_cannot_be_accepted` | 2026-11-04 |
| Each bundle meets a named read-only control, and enabled servers match it | `tests/test_readonly_contract.py::test_bundle_satisfies_its_declared_control`, `tests/test_doctor.py::test_removed_readonly_suffix_fails` | 2026-06-07 |
| Every bundle's claude.ai connector write tools are denied in the shared `.claude/settings.json` | `tests/test_source_bundles.py::test_setup_denies_every_bundles_connector_writes_in_shared_settings` | 2026-11-06 |
| No permission-bypass flag ships | `tests/test_readonly_contract.py::test_no_permission_bypass_flag_ships_anywhere` | 2026-11-04 |
| Layers hold, and models forbid unknown fields | `make boundaries`, `make lint` (ruff TID251 bans pydantic.BaseModel) | 2026-11-04 |
| Instruction text stays under its limit, and doc links resolve | `tests/test_docs_contract.py::test_all_instruction_text_stays_under_the_limit`, `tests/test_docs_contract.py::test_relative_doc_links_resolve` | 2026-11-04 |
| `make verify` can fail: its control asserts a wrong result and must observe FAIL | `.agents/skills/verify-fact-finder/verify::control` | 2026-11-06 |
| No file downgrades strict type checking with a `# pyright:` mode comment | `tests/test_strict_mode.py::test_no_file_downgrades_type_checking_mode` | 2026-11-07 |
