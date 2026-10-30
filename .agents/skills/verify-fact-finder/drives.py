"""Per-feature drive logic for the verify helper. Each drive uses only the public CLI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor."
)
FILLED_REPORT = """# Report

## Executive Summary

Failures rose from 100 to 412 in June after the scheduler change, in one cohort. [C1]

## Evidence

Weekly counts from the export.

## Reconciliation

Cohorts sum to 412, and the change log and cohorts explain why.

## Rejected Leads

Storage quota stayed flat.

## Risks And Caveats

One static export.
"""


def new_case(drive: Any, slug: str) -> Path:
    out = drive.expect(
        [
            "init",
            slug,
            "--question",
            "Why did failures rise in June?",
            "--local-only",
            "--rigour",
            "decision",
        ],
        0,
    )
    return Path(out.split("Path: ", 1)[1].splitlines()[0])


def fill(drive: Any, case: Path, reviewer: str = "task-reviewer-a4f21") -> None:
    artifact = b'{"May": 100, "June": 412}\n'
    locator = "exports/weekly.csv"
    (case / "evidence").mkdir(exist_ok=True)
    (case / "evidence" / "weekly.json").write_bytes(artifact)
    (case / "report.md").write_text(FILLED_REPORT)
    (case / "queries.sql").write_text("-- No SQL used: a CSV export.\n")
    (case / "source-objects.md").write_text(
        f"# Source Objects\n\n- `{locator}` (accessed 2026-08-17)\n"
    )
    evidence = {
        "schema_version": 1,
        "sources": [
            {
                "id": "S1",
                "family": "local",
                "route": "file",
                "locator": locator,
                "accessed_at": "2026-08-17T09:00:00Z",
                "independence_group": "export",
                "artifact": "evidence/weekly.json",
                "sha256": hashlib.sha256(artifact).hexdigest(),
            }
        ],
        "coverage": [
            {
                "family": "local",
                "status": "used",
                "reason": "Local case.",
                "consequence": "No live check.",
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
                "result": "312",
                "unit": "jobs",
                "inputs": [
                    {"name": "June", "value": "412", "unit": "jobs", "source_id": "S1"},
                    {"name": "May", "value": "100", "unit": "jobs", "source_id": "S1"},
                ],
            }
        ],
    }
    (case / "evidence.json").write_text(json.dumps(evidence))
    brief = (case / "brief.md").read_text().replace("\nnone\n", "\nlocal\n")
    (case / "brief.md").write_text(brief)
    hashes = json.loads(drive.expect(["review-snapshot", case.name], 0))
    (case / "review.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "reviewer": reviewer,
                "reviewed_hashes": hashes,
                "objections": [],
                "strongest_alternative": "Seasonality.",
                "weakest_claim": "C1.",
                "fragile_dependency": "One export.",
                "verdict": "pass",
            }
        )
    )


def lorem(case: Path) -> None:
    (case / "report.md").write_text(
        "# R\n\n"
        + "".join(
            f"## {h}\n\n{LOREM}\n\n"
            for h in (
                "Executive Summary",
                "Evidence",
                "Reconciliation",
                "Rejected Leads",
                "Risks And Caveats",
            )
        )
    )
    (case / "notes.md").write_text(
        f"## Evidence Log\n\n- Claim: {LOREM}\n  - Source: {LOREM}\n  - Supports: x\n\n"
        "## Final Challenge\n\n- Independent reviewer: claude\n"
    )
    (case / "queries.sql").write_text("-- No SQL used: lorem\n")
    (case / "source-objects.md").write_text(f"# Source Objects\n\n- {LOREM}\n")


def drive_case_lifecycle(drive: Any) -> None:
    case = new_case(drive, "lifecycle")
    drive.expect(["goal", case.name], 0, "/goal", str(case))
    drive.expect(["validate", case.name], 0, "Validation passed")
    drive.expect(
        ["validate", case.name, "--strict"], 1, "independent review is missing"
    )
    drive.expect(["list"], 0, "lifecycle  in-progress")
    fill(drive, case)
    drive.expect(["validate", case.name, "--strict"], 0, "cannot be proved by a gate")
    drive.expect(["list"], 0, "lifecycle  decision-complete")
    with (case / "report.md").open("a") as report:
        report.write("\nLate edit.\n")
    drive.expect(["validate", case.name, "--strict"], 0, "stale for report.md")
    drive.expect(
        ["validate", case.name, "--strict", "--pinned"], 1, "stale for report.md"
    )
    payload = json.loads(
        drive.expect(["validate", case.name, "--strict", "--pinned", "--json"], 1)
    )
    drive.check(payload["passed"] is False, "--json did not report the failure")
    drive.expect(["list"], 0, "lifecycle  decision-stale-review")


def drive_quick_answer(drive: Any) -> None:
    out = drive.expect(
        ["init", "quick", "--question", "Did failures rise?", "--local-only"], 0
    )
    case = Path(out.split("Path: ", 1)[1].splitlines()[0])
    report = case / "report.md"
    report.write_text(
        report.read_text().replace(
            "<!-- research:placeholder --> Complete this section with the answer and the most "
            "decision-relevant evidence.",
            "Yes. Failures rose from 100 to 412 a week after the June scheduler change.",
        )
    )
    drive.expect(
        ["validate", case.name, "--strict"],
        0,
        "Exploratory answer: no independent review",
    )
    (case / "queries.sql").write_text("DROP TABLE t")
    drive.expect(
        ["validate", case.name, "--strict", "--accept", "try"], 1, "not read-only"
    )
    drive.check(not (case / "overrides.json").exists(), "safety was overridden")


def drive_lorem_gate(drive: Any) -> None:
    case = new_case(drive, "filler")
    lorem(case)
    drive.expect(
        ["validate", case.name, "--strict"],
        1,
        "independent review is missing",
        "has no locator or access date",
    )
    named = new_case(drive, "named")
    fill(drive, named, reviewer="claude")
    drive.expect(
        ["validate", named.name, "--strict"], 1, "names no independent reviewer"
    )


def drive_sql_gate(drive: Any) -> None:
    case = new_case(drive, "sql")
    for sql in (
        r"SELECT 'a\'; DROP TABLE t; --'",
        "USE ROLE ACCOUNTADMIN",
        "EXPLAIN ANALYZE DELETE FROM t",
    ):
        (case / "queries.sql").write_text(sql)
        drive.note(f"queries.sql: {sql}")
        drive.expect(["validate", case.name], 1, "not read-only", forbid=("Traceback",))
    for sql in (
        r"SELECT 'dir\' AS p",
        "USE WAREHOUSE ANALYTICS",
        'SELECT 1 AS "NEXTVAL"',
    ):
        (case / "queries.sql").write_text(sql)
        drive.note(f"queries.sql: {sql}")
        drive.expect(["validate", case.name], 0, "Validation passed")


def drive_sources(drive: Any) -> None:
    drive.expect(["source", "enable", "github"], 0, "wired server 'github'")
    drive.expect(["source", "enable", "stripe"], 0, "denied 4 write tools")
    drive.check(
        "mcp__stripe__create_refund"
        in (drive.target / ".claude/settings.local.json").read_text(),
        "no Claude deny rule",
    )
    drive.check(
        "disabled_tools" in (drive.target / ".codex/config.toml").read_text(),
        "no Codex deny list",
    )
    drive.expect(
        ["doctor"], 0, "[PASS] github", "[DECLARED] stripe", "does not contact"
    )
    mcp = drive.target / ".mcp.json"
    good = mcp.read_text()
    mcp.write_text(good.replace("/mcp/readonly", "/mcp"))
    drive.expect(["doctor"], 1, "url does not end with /readonly", "Fix:")
    mcp.write_text(good)
    drive.expect(["source", "disable", "stripe"], 0, "removed source 'stripe'")
    sources = drive.target / "config" / "sources.json"
    kept = sources.read_text()
    sources.write_text("{bad")
    drive.expect(
        ["source", "disable", "github"],
        1,
        "config/sources.json",
        "Fix:",
        forbid=("Traceback",),
    )
    sources.write_text(kept)
    drive.expect(["source", "disable", "github"], 0)


def drive_consumer_setup(drive: Any) -> None:
    drive.expect(["setup"], 0, "linked research-goal into .agents/skills")
    drive.expect(["setup"], 0, "nothing to do", forbid=("wired",))
    drive.expect(["contract", "method"], 0, "# Research method")
    drive.expect(["contract", "evidence"], 0, "review-snapshot")
    drive.check(
        any(drive.target.parent.glob("venv/lib/*/site-packages/fact_finder/py.typed")),
        "the wheel has no py.typed",
    )
    for name in ("research-goal", "research-spec"):
        skill = drive.target / ".agents" / "skills" / name / "SKILL.md"
        drive.check(
            skill.exists() and f"name: {name}" in skill.read_text(),
            f"{name} did not link from the wheel",
        )
        drive.check(
            not (drive.target / ".agents" / "skills" / name).readlink().is_absolute(),
            f"{name} link is absolute",
        )
    drive.check(
        (drive.target / ".claude" / "skills" / "research-goal" / "SKILL.md").exists(),
        "Claude cannot see the skill",
    )
    drive.expect(["source", "list"], 0, "azure-devops", "google-drive", "microsoft-365")


def drive_agent_feedback(drive: Any) -> None:
    """Scaffold a source, follow `next`, and get concrete feedback from the installed hook."""
    drive.expect(["source", "new", "zendesk"], 0, "zendesk.toml")
    drive.expect(["source", "enable", "zendesk"], 1, "still marked TODO", "Fix:")
    bundle = drive.target / "examples" / "sources" / "zendesk.toml"
    drive.expect(["lint", str(bundle)], 1, "still marked TODO")
    bundle.write_text(bundle.read_text().replace("TODO: ", ""))
    drive.expect(["source", "enable", "zendesk"], 0, "added source 'zendesk'")
    drive.expect(["source", "disable", "zendesk"], 0)
    drive.expect(["next"], 0, "research init <slug>")
    drive.expect(
        ["init", "q", "--local-only", "--question", "Why?"], 0, "research next"
    )
    case = next((drive.target / "research").glob("*-q"))
    drive.expect(["next", case.name], 0, "research goal")
    (case / "queries.sql").write_text("-- note\nDROP TABLE t;\n")
    drive.expect(["next", case.name], 0, "queries.sql:2: not read-only", "Fix:")
    drive.expect(["lint", str(case / "queries.sql")], 1, "queries.sql:2: not read-only")
    drive.expect(["setup"], 0, "added the edit hook to .claude/settings.json")
    drive.check(
        "report-edit.sh claude"
        in (drive.target / ".claude" / "settings.json").read_text(),
        "no Claude hook",
    )
    drive.check(
        (drive.target / ".agents" / "hooks" / "report-edit.sh").exists(),
        "the hook script did not link from the wheel",
    )


FEATURES = {
    "agent-feedback": drive_agent_feedback,
    "case-lifecycle": drive_case_lifecycle,
    "quick-answer": drive_quick_answer,
    "lorem-gate": drive_lorem_gate,
    "sql-gate": drive_sql_gate,
    "sources": drive_sources,
    "consumer-setup": drive_consumer_setup,
}
