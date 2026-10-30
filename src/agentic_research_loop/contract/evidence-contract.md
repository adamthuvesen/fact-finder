# Evidence and review contract

This contract applies to a decision case, created with `research init --rigour decision`. An
exploratory case needs only a labelled `report.md`. `research schema evidence` and
`research schema review` print the authoritative fields. Validation names each gap and its fix.

## Preserve evidence

Save aggregate results or source excerpts inside the case, such as `evidence/monthly-counts.json`.
A summary written from memory is not a preserved query result. Retain row counts, column metadata,
truncation indicators, and filters. Do not save credentials, unnecessary personal data, or entire
documents when a small excerpt supports the claim. Keep query text in `queries.sql`.

Sources derived from the same upstream instrumentation share an `independence_group`. Different
tools or tables do not automatically provide independent evidence.

## Fill the manifest

Record a contribution's denominator explicitly. Gross positive movement, signed net movement, and
baseline volume answer different questions. Use zero tolerance for exact counts, and justify a
nonzero tolerance in the report. Difference subtracts the second input from the first. Ratio
outputs use unit `ratio`, so 50% is `0.5`.

A causal label does not certify identification. Explain the identification strategy and unresolved
confounders in the report. Place each claim's marker beside the statement it supports.

## Independent final challenge

Give a reviewer the brief, report, manifest, preserved evidence, and SQL. The reviewer must not
have conducted the investigation. Ask it to recompute fragile calculations and inspect original
evidence where access permits. It checks:

1. Whether each material claim follows from the cited evidence.
2. Whether the report omits material contradictions or source limitations.
3. Whether purported corroboration shares the same upstream dependency.
4. Whether causal language exceeds the identification strategy.
5. Whether the conclusion helps the reader make the stated decision.

`research review-snapshot <case>` prints the hashes for `review.json`. It approves nothing. Record
the actual reviewer's subagent name or task id: a generic name fails. Resolve a `blocking` objection,
narrow the conclusion, or make the answer explicitly inconclusive. If reviewed content changes, ask
the reviewer to inspect the final version. Never replace a hash without that review.

## What blocks

Run `research validate <case> --strict`.

- **Always, with no override:** write SQL, unreadable `queries.sql`, an artifact outside the case,
  and a missing `brief.md` or `report.md`.
- **Both rigour levels:** no real Executive Summary, wrong arithmetic, and a missing required brief
  section. An exploratory case also needs its label.
- **Decision only:** the manifest, the review, report sections, artifact hashes, and a preserved
  query for a used SQL-backed family.
- **On request:** a review older than the latest edits, with `--pinned`.
- **Everything else warns.**

A person can accept a rigour block with `--accept "<short reason>"`. It goes in `overrides.json`, in
an `## Accepted Gaps` section of `report.md`, and in the result label. A later, different problem
still blocks.

Validation cannot prove semantic truth, causal identification, or reviewer independence. A
consistent manifest full of filler with a plausible reviewer id still passes. The reviewer name is
an attestation.

A brief with no `- Rigour:` line is a decision case.
