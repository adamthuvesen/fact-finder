# Evidence and review contract

This contract applies to a decision case, created with `research init --rigour decision`. An
exploratory case needs only a labelled `report.md`. Files it does carry are still checked.

Use Markdown to explain the answer. Use `evidence.json` to connect material claims to preserved evidence and calculations.

Inspect the authoritative schemas with:

```bash
uv run research schema evidence
uv run research schema review
```

## Preserve evidence

Save relevant aggregate results or source excerpts inside the case, such as `evidence/monthly-counts.json`. Record the retrieval route, source locator, access time, query ID when available, and SHA-256 digest. Keep query text in `queries.sql`.

A decision case that marks a SQL-backed family as `used` needs at least one preserved query, and `-- No SQL used` does not satisfy it. The SQL-backed families are those whose bundle sets `sql_backed`: Snowflake, BigQuery, Postgres, DuckDB, and Redshift. Other query languages, such as KQL, and natural-language endpoints are not parsed as SQL.

A source with a `query_id` needs a matching `-- query_id: <id>` comment directly above a statement in `queries.sql`. An id with no statement, or inside a string literal, does not count. Every source `locator` must match an entry in `source-objects.md`. An entry is one bullet: a backticked name or a URL, then `accessed YYYY-MM-DD`.

Do not save credentials, unnecessary personal data, or entire documents when a small excerpt supports the claim. Retain row counts, column metadata, truncation indicators, and filters needed to interpret the result. A summary written from memory is not a preserved query result.

Sources derived from the same upstream instrumentation share an `independence_group`. Different tools or tables do not automatically provide independent evidence.

## Fill the manifest

The schema has four collections:

- `sources`: source identity, route, locator, access time, independence group, and preserved artifact digest.
- `coverage`: one disposition for every allowed source family. Use `used`, `unavailable`, or `not-needed`, with a reason and consequence.
- `claims`: concise material statements, source and calculation references, limitations, and report markers such as `[C1]`.
- `calculations`: named numeric inputs with units and sources, operation, expected result, and tolerance.

Use `sum`, `difference`, or `ratio`. Difference subtracts the second input from the first. Ratio divides the other input by the named denominator. Ratio outputs use unit `ratio`, so 50% is `0.5`. Use zero tolerance for exact counts. Justify a nonzero tolerance in the report.

Record a contribution's denominator explicitly. Gross positive movement, signed net movement, and baseline volume answer different questions.

A claim can be `descriptive` or `causal`. Its status is `supported` or `inconclusive`. Causal and inconclusive claims require limitations. A causal label does not certify identification. Explain the identification strategy and unresolved confounders in the report.

Place each claim's marker beside the relevant report statement. The reviewer must detect uncited material claims and citations that do not support the prose.

The brief's `Allowed Source Families` section binds coverage and source scope. Use `local` for explicitly allowed local inputs. Adding an available connector does not extend the brief.

## Independent final challenge

Give a reviewer the brief, report, manifest, preserved evidence, and SQL. The reviewer should not have conducted the investigation. Ask it to recompute fragile calculations and inspect original source evidence where access permits.

The reviewer checks:

1. Whether each material claim follows from the cited evidence.
2. Whether the report omits material contradictions or source limitations.
3. Whether purported corroboration shares the same upstream dependency.
4. Whether causal language exceeds the identification strategy.
5. Whether the conclusion helps the reader make the stated decision.

Get the current artifact fingerprints:

```bash
uv run research review-snapshot <case>
```

This command only prints hashes. It does not approve the case or create `review.json`.

Record the actual reviewer identity, fingerprints, strongest alternative, weakest claim, fragile dependency, objections, dispositions, and verdict in `review.json`. `review.json` is the only record of the final challenge, and `evidence.json` is the only record of evidence. Validation does not read `notes.md`. A generic name such as `claude`, `codex`, or `main agent` fails. Use the subagent name or task id. A `blocking` objection prevents a passing review. Resolve it, narrow the conclusion, or make the answer explicitly inconclusive.

If reviewed content changes, ask the reviewer to inspect the final version. Never replace hashes without that review. Hashes detect stale content but cannot prove reviewer independence or honest review.

## Validation and limits

```bash
uv run research validate <case> --strict
```

| Finding | Exploratory | Decision |
| --- | --- | --- |
| Write SQL, unreadable `queries.sql`, or an artifact outside the case | blocks, no override | blocks, no override |
| Missing or unreadable `brief.md` or `report.md` | blocks, no override | blocks, no override |
| No real Executive Summary | blocks | blocks |
| Missing exploratory label in `report.md` | blocks | not applicable |
| Wrong arithmetic in `evidence.json` | blocks | blocks |
| Missing or invalid `evidence.json` or `review.json`, or a generic reviewer name | not required | blocks |
| Blocked review verdict, changed artifact, or empty report section | warns | blocks |
| A used SQL-backed family with no preserved query | warns | blocks |
| Reviewed file changed since the review | warns | warns; blocks with `--pinned` |
| Query id, source-object format, coverage text, claim marker, root-cause sections, shape | warns | warns |

To accept a block, a person runs `validate <case> --strict --accept "<short reason>"`. Each accepted
finding and its reason go in `overrides.json`, in an `## Accepted Gaps` section the command writes at
the end of `report.md`, and in the result label. A reader of the report sees them without running a
command. That section is not part of a reviewed hash. A later, different problem still blocks.

Semantic truth and reviewer independence cannot be proved by a gate. Validation does not verify external truth, semantic entailment, or causal identification. A structurally consistent manifest full of filler, with a plausible reviewer id, still passes. The reviewer name is an attestation. Independent challenge and research evaluations test what deterministic validation cannot establish.

## Existing cases

A brief with no `- Rigour:` line is a decision case. To finish one as a decision, add the brief's `## Allowed Source Families`, recover actual evidence and calculation inputs, and obtain a new review. If evidence cannot be recovered, disclose the limit rather than reconstructing a result from recollection. Non-strict validation still reads older cases.

Legacy `state/` files remain historical records. They do not control execution or completion.
