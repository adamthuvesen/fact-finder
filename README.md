# Fact Finder

![License](https://img.shields.io/github/license/adamthuvesen/fact-finder) ![Python](https://img.shields.io/badge/python-3.14%2B-blue)

A research kit for bounded investigations. Give it a question and a set of read-only
sources. It creates a workspace, frames the case, and validates the evidence the
investigation leaves behind.

Execution runs inside your agent client's native `/goal`. The client owns persistence
and continuation. This repo owns the research contract, read-only source access, durable
artifacts, and deterministic validation. There is no subprocess runner and no second
agent loop. [The decision record](.agents/docs/decisions/native-goals.md) explains why.

## Quick start (no API keys, no MCP)

```bash
uv sync --dev

uv run research init export-reliability --template root-cause \
  --question "Why did the weekly batch-export success rate drop in March 2026?" \
  --local-only --context-path examples/local-sources

uv run research next export-reliability
```

Run the printed `research goal` command, and paste its `/goal` block into Claude Code or Codex from
the repo root. A finished
decision case is in [`examples/demo-export-reliability/`](examples/demo-export-reliability/).

## Run inside Claude Code or Codex

Submit one native goal from the repository root. Claude Code names the skill as
`the research-goal skill`, and Codex names it as `$research-goal`:

```text
/goal Use the research-goal skill to investigate:

Why did the weekly batch-export success rate drop in March 2026? Use only the local files under examples/local-sources. Stop when the largest cause is named with reconciling numbers and strict validation passes.
```

For an ambiguous, causal, cross-source, or high-stakes question, name `research-spec`
instead. It runs targeted discovery and designs falsifiable hypotheses first.

## Quick answers and decisions

```bash
uv run research init churn-check --question "Did churn rise in June?"   # exploratory
# write the answer in report.md
uv run research validate churn-check --strict
```

An exploratory case passes with a real answer and its label line. It needs no evidence manifest
or review, and warnings list what would make it stronger. For a decision that matters, use
`research init --rigour decision`. That adds `evidence.json` and an independent `review.json`.

Safety is hard: write SQL fails, always. Rigour is a default: a person can accept a block with
`--accept "<reason>"`, which is recorded and labelled. A gate proves integrity and arithmetic,
not truth, and its output says so. `uv run research contract evidence` prints the contract.

## Sources

Only web search is built in. Local files attach per case with `--context-path`. Everything else is
an opt-in, read-only bundle that names its control. `uv run research source list` shows them.
`research source enable <name>` generates every client's config and write-tool deny list from one
definition, and `research source show <name>` prints its setup steps.

## CLI

`uv run research --help` lists every command. `uv run research next` prints the next useful step.

## Use from another repo

Add this package pinned by git SHA, add a `[tool.fact-finder]` table to your `pyproject.toml`,
and run `uv run research setup`. That table extends the engine with no engine change:

```toml
[tool.fact-finder]
required_brief_fields = ["Owner"]  # research init scaffolds them and validate checks them
sources_dir = "sources"            # your own or overriding bundles; default examples/sources
gsc_site = "https://www.example.com/"
ga4_property_id = "123456789"
```

[Setup](.agents/docs/setup.md) covers a local engine checkout.

## Development

[AGENTS.md](AGENTS.md) holds the commands, boundaries, and enforced rules. `make check` is the gate. `make quick` checks only what changed. Client goal behavior is an external
dependency, so [`evals/native-goal/`](evals/native-goal/README.md) holds a blind, keyless canary.

## License

[Apache 2.0](LICENSE) © 2026 Adam Thuvesen
