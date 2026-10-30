"""Build a complete case on disk, the same shape a finished goal leaves behind."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fact_finder.evidence import review_snapshot

QUESTION = "Why did weekly export failures rise in June 2026?"

BRIEF = f"""\
# Research Brief

## Question

{QUESTION}

## Scope

- Research shape: `exploration`

## Source Constraints

- Local context folder: /tmp/exports

## Allowed Source Families

local
"""

REPORT = """\
# Research Report

## Question

Why did weekly export failures rise in June 2026?

## Executive Summary

Weekly export failures rose from 100 to 412 in June, concentrated in the
large-workspace cohort after the June 3 scheduler change. [C1]

## Ranked Causes

1. The June 3 scheduler change.

## Evidence

Failure counts by week, from the weekly export.

## Reconciliation

Cohort failures sum to 412, matching the 412 total in the export.

## Rejected Leads

Storage quota: flat across the whole window.

## Risks And Caveats

A single static export; no live system cross-check was possible.
"""

NOTES = "# Research Notes\n\n## Working Theory\n\n- The scheduler change.\n"
QUERIES = "-- No SQL used: the case reads a CSV export directly.\n"
LOCATOR = "examples/local-sources/exports_weekly.csv"
SOURCE_OBJECTS = f"# Source Objects\n\n- `{LOCATOR}` (accessed 2026-08-17)\n"


def evidence_document(artifact: bytes) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "sources": [
            {
                "id": "S1",
                "family": "local",
                "route": "read local CSV",
                "locator": LOCATOR,
                "accessed_at": "2026-08-17T09:00:00Z",
                "independence_group": "weekly-export",
                "artifact": "evidence/weekly.json",
                "sha256": hashlib.sha256(artifact).hexdigest(),
            }
        ],
        "coverage": [
            {
                "family": "local",
                "status": "used",
                "reason": "The case allows only local files.",
                "consequence": "No live cross-check.",
            }
        ],
        "claims": [
            {
                "id": "C1",
                "statement": "Failures rose by 312.",
                "kind": "descriptive",
                "source_ids": ["S1"],
                "calculation_ids": ["D1"],
                "limitations": [],
                "status": "supported",
                "report_marker": "[C1]",
            }
        ],
        "calculations": [
            {
                "id": "D1",
                "operation": "difference",
                "inputs": [
                    {"name": "June", "value": "412", "unit": "jobs", "source_id": "S1"},
                    {"name": "May", "value": "100", "unit": "jobs", "source_id": "S1"},
                ],
                "result": "312",
                "unit": "jobs",
            }
        ],
    }


def review_document(case: Path, reviewer: str = "independent-challenger-17") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "reviewer": reviewer,
        "reviewed_hashes": review_snapshot(case),
        "objections": [
            {
                "objection": "A seasonal spike could explain June.",
                "disposition": "narrowed",
                "resolution": "The claim describes counts and makes no causal inference.",
            }
        ],
        "strongest_alternative": "A seasonal volume spike.",
        "weakest_claim": "C1 depends on one export.",
        "fragile_dependency": "The single CSV export.",
        "verdict": "pass",
    }


def write_review(case: Path, **overrides: object) -> None:
    document = {**review_document(case), **overrides}
    (case / "review.json").write_text(json.dumps(document), encoding="utf-8")


def fill_case(
    case: Path,
    *,
    brief: str = BRIEF,
    report: str = REPORT,
    queries: str = QUERIES,
    source_objects: str = SOURCE_OBJECTS,
) -> Path:
    """Write every artifact into `case` and record a fresh review of them."""
    case.mkdir(parents=True, exist_ok=True)
    (case / "brief.md").write_text(brief, encoding="utf-8")
    (case / "notes.md").write_text(NOTES, encoding="utf-8")
    (case / "report.md").write_text(report, encoding="utf-8")
    (case / "queries.sql").write_text(queries, encoding="utf-8")
    (case / "source-objects.md").write_text(source_objects, encoding="utf-8")
    artifact = b'{"May": 100, "June": 412}\n'
    (case / "evidence").mkdir(exist_ok=True)
    (case / "evidence" / "weekly.json").write_bytes(artifact)
    (case / "evidence.json").write_text(json.dumps(evidence_document(artifact)), encoding="utf-8")
    write_review(case)
    return case


def fill_with_lorem_ipsum(case: Path) -> Path:
    """Write the filler case that the old notes.md gate passed in strict mode."""
    lorem = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
        "tempor incididunt ut labore et dolore magna aliqua."
    )
    (case / "brief.md").write_text(
        BRIEF.replace(QUESTION, "Lorem ipsum dolor sit amet?"), encoding="utf-8"
    )
    (case / "report.md").write_text(
        "# Research Report\n\n"
        + "".join(
            f"## {heading}\n\n{lorem}\n\n"
            for heading in (
                "Executive Summary",
                "Evidence",
                "Reconciliation",
                "Rejected Leads",
                "Risks And Caveats",
            )
        ),
        encoding="utf-8",
    )
    (case / "notes.md").write_text(
        f"""# Research Notes

## Evidence Log

- Claim: {lorem}
  - Source: {lorem}
  - Supports: lorem
  - Caveat or freshness limit: ipsum

## Final Challenge

- Independent reviewer: claude
- Strongest competing explanation: {lorem}
- Weakest-supported material claim: {lorem}
- Most fragile source or calculation: {lorem}
- Resolution: resolved lorem ipsum
""",
        encoding="utf-8",
    )
    (case / "queries.sql").write_text("-- No SQL used: lorem ipsum\n", encoding="utf-8")
    (case / "source-objects.md").write_text(f"# Source Objects\n\n- {lorem}\n", encoding="utf-8")
    return case
