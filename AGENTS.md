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
- an edit to a check that would allow one of the above

Stop. Say which recorded decision the request reverses, such as
`.agents/docs/decisions/native-goals.md` or this file. Offer an option that keeps the boundary.

## Running research

Start from a native `/goal` naming `research-goal`, or `research-spec` when scope needs discovery
first. When a goal is active, adopt the generated contract and finish in that session. Do not
stop after scaffolding or submit a nested goal. Run the CLI from the repo root. The rules for a
case live in one place, `uv run research contract method`.

## Enforced rules

| Rule | Enforced by | Added |
| --- | --- | --- |
| No agent SDK import or process spawn, except `scripts/check_agent_setup.py`, which asks clients for versions | `pyproject.toml` (ruff TID251), `rules/no-dynamic-import.yml` | 2026-11-04 |
| Pydantic models subclass `StrictModel`, which forbids extra fields | `pyproject.toml` (ruff TID251), `rules/strict-model-only.yml` | 2026-11-04 |
| cli above domain above I/O; nothing imports cli | `make boundaries` | 2026-11-04 |
| Preserved SQL is read-only under every dialect reading | `tests/test_readonly_sql.py` | 2026-11-04 |
| Claims cite declared sources; query ids exist; review is fresh | `tests/test_evidence.py` | 2026-11-04 |
| A lorem ipsum case or reviewer `claude` fails strict | `tests/test_end_to_end.py` | 2026-11-04 |
| Each bundle meets a named read-only control from a closed set | `tests/test_readonly_contract.py` | 2026-11-04 |
| Enabled servers match their bundle and control | `tests/test_doctor.py` | 2026-11-04 |
| `.mcp.json` ships neutral | `tests/test_mcp_configs_consistent.py` | 2026-11-04 |
| Source lists are generated, never hand-edited | `tests/test_source_catalog.py` | 2026-11-04 |
| No permission-bypass flag ships | `tests/test_readonly_contract.py` | 2026-11-04 |
| Goal contract paths are absolute | `tests/test_cli.py` | 2026-11-04 |
| Instruction lines stay under 500; relative doc links resolve; skills keep their hard limits | `tests/test_docs_contract.py` | 2026-11-04 |
