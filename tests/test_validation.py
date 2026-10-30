from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

import pytest
from support.cases import (
    BRIEF,
    QUESTION,
    REPORT,
    SOURCE_OBJECTS,
    fill_case,
    write_review,
)
from support.checks import validate_case

from agentic_research_loop.templates import (
    EXPLORATORY_LABEL,
    PLACEHOLDER,
    notes_template,
    queries_template,
    report_template,
    source_objects_template,
)
from agentic_research_loop.validation import (
    accept_findings,
    assess_case,
    parse_source_objects,
)


def build_case(tmp_path: Path, **artifacts: str) -> Path:
    return fill_case(tmp_path / "2026-08-17-exports", **artifacts)


def warnings_of(case: Path) -> list[str]:
    return assess_case(case, strict_completion=True).warnings


def test_complete_case_passes_strict(tmp_path: Path) -> None:
    assert validate_case(build_case(tmp_path), strict_completion=True) == []


def test_missing_report_blocks_and_missing_notes_warn(tmp_path: Path) -> None:
    case = build_case(tmp_path)
    (case / "notes.md").unlink()
    assert validate_case(case, strict_completion=True) == []
    assert any("notes.md: the file is missing" in item for item in warnings_of(case))

    (case / "report.md").unlink()

    assert any("report.md: the file is missing" in e for e in validate_case(case))


def test_notes_carry_no_gate(tmp_path: Path) -> None:
    """review.json owns the challenge and evidence.json owns the evidence."""
    case = build_case(tmp_path)
    (case / "notes.md").write_text("# Notes\n", encoding="utf-8")

    assert validate_case(case, strict_completion=True) == []


def test_write_sql_is_rejected_without_strict(tmp_path: Path) -> None:
    case = build_case(
        tmp_path,
        queries="SELECT week FROM exports;\nDELETE FROM exports WHERE week = 1;\n",
    )

    assert any("not read-only" in error for error in validate_case(case))


def test_write_keyword_inside_a_string_literal_is_allowed(tmp_path: Path) -> None:
    case = build_case(
        tmp_path, queries="SELECT * FROM audit WHERE action = 'delete';\n"
    )

    assert validate_case(case, strict_completion=True) == []


def test_use_warehouse_is_allowed_because_the_shipped_allowlist_permits_it(
    tmp_path: Path,
) -> None:
    case = build_case(
        tmp_path, queries="USE WAREHOUSE ANALYTICS;\nSELECT count(*) FROM exports;\n"
    )

    assert validate_case(case, strict_completion=True) == []


def test_missing_sql_reason_warns(tmp_path: Path) -> None:
    case = build_case(tmp_path, queries="-- nothing preserved here\n")

    assert validate_case(case, strict_completion=True) == []
    assert any("No SQL used" in warning for warning in warnings_of(case))


def test_placeholder_question_warns(tmp_path: Path) -> None:
    case = build_case(tmp_path, brief=BRIEF.replace(QUESTION, "Research: exports"))

    assert any(
        "question is still the scaffold text" in warning
        for warning in warnings_of(case)
    )


def test_strict_rejects_an_unwritten_report_section(tmp_path: Path) -> None:
    written = "Cohort failures sum to 412, matching the 412 total in the export."
    case = build_case(
        tmp_path, report=REPORT.replace(written, f"{PLACEHOLDER} Show it.")
    )

    errors = validate_case(case, strict_completion=True)

    assert any("Reconciliation" in error for error in errors)


def test_real_text_containing_explain_why_passes(tmp_path: Path) -> None:
    """The old check matched template wording, so this honest sentence failed."""
    written = "Cohort failures sum to 412, matching the 412 total in the export."
    case = build_case(
        tmp_path,
        report=REPORT.replace(
            written, f"{written} The change log and cohorts explain why."
        ),
    )

    assert validate_case(case, strict_completion=True) == []


def test_root_cause_design_sections_warn(tmp_path: Path) -> None:
    case = build_case(tmp_path, brief=BRIEF.replace("`exploration`", "`root-cause`"))

    warnings = warnings_of(case)

    assert any("Hypotheses" in warning for warning in warnings)
    assert any("Known Confounders" in warning for warning in warnings)
    assert any("Required Cross-Checks" in warning for warning in warnings)


def test_high_priority_thread_without_a_discriminating_test_warns(
    tmp_path: Path,
) -> None:
    brief = BRIEF.replace("`exploration`", "`root-cause`") + textwrap.dedent("""
        ## Hypotheses

        - H1

        ## Known Confounders

        - Seasonality

        ## Required Cross-Checks

        - Second source
        """)
    case = build_case(tmp_path, brief=brief)
    (case / "plan.md").write_text(
        textwrap.dedent("""\
            # Research Plan

            ### T1: Scheduler change
            **Priority:** high
            **Strongest Rival:** Seasonal spike
            **Completion Threshold:** done when the cohort is named
            **Cross-Check:** change log
            """),
        encoding="utf-8",
    )

    assert any("Discriminating Test" in warning for warning in warnings_of(case))


DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo-export-reliability"


def test_demo_passes_with_its_review_pinned() -> None:
    assert assess_case(DEMO, strict_completion=True, pinned=True).errors == []


@pytest.mark.parametrize(
    "name", ["brief.md", "report.md", "queries.sql", "evidence/windows.json"]
)
def test_a_demo_edit_makes_its_review_stale(tmp_path: Path, name: str) -> None:
    case = tmp_path / "demo"
    shutil.copytree(DEMO, case)
    with (case / name).open("a", encoding="utf-8") as handle:
        handle.write("\n")

    assert any(
        f"stale for {name}" in error
        for error in assess_case(case, strict_completion=True, pinned=True).errors
    )


def test_untouched_shipped_templates_fail_the_completion_gate(tmp_path: Path) -> None:
    case = build_case(tmp_path)
    (case / "notes.md").write_text(notes_template(), encoding="utf-8")
    (case / "report.md").write_text(
        report_template("exploration", "Why?"), encoding="utf-8"
    )
    (case / "queries.sql").write_text(queries_template(), encoding="utf-8")
    (case / "source-objects.md").write_text(source_objects_template(), encoding="utf-8")

    errors = validate_case(case, strict_completion=True)

    assert any("Executive Summary" in error for error in errors)
    assert any("source-objects.md" in warning for warning in warnings_of(case))
    assert any("No SQL used" in warning for warning in warnings_of(case))


def test_an_unreadable_research_shape_warns(tmp_path: Path) -> None:
    case = build_case(
        tmp_path,
        brief=BRIEF.replace(
            "- Research shape: `exploration`", "- Research shape: `bogus`"
        ),
    )

    assert any("unknown research shape" in warning for warning in warnings_of(case))


def test_missing_research_shape_warns(tmp_path: Path) -> None:
    case = build_case(
        tmp_path, brief=BRIEF.replace("- Research shape: `exploration`\n", "")
    )

    assert any("Research shape" in warning for warning in warnings_of(case))


@pytest.mark.parametrize(
    "shape_line",
    [
        "- **Research shape:** `root-cause`",
        "- **Research shape**: `root-cause`",
        "- Research shape: `root-cause` (metric regression)",
        "- Research shape: `Root-Cause`",
    ],
)
def test_research_shape_survives_bold_and_trailing_text(
    tmp_path: Path, shape_line: str
) -> None:
    case = build_case(
        tmp_path, brief=BRIEF.replace("- Research shape: `exploration`", shape_line)
    )

    assert any("Hypotheses" in warning for warning in warnings_of(case))


def test_select_into_is_rejected(tmp_path: Path) -> None:
    case = build_case(
        tmp_path, queries="SELECT week INTO exports_snapshot FROM exports;\n"
    )

    assert any("INTO" in error for error in validate_case(case))


def test_coverage_mismatch_warns(tmp_path: Path) -> None:
    case = build_case(tmp_path, brief=BRIEF.replace("\nlocal\n", "\nlocal, slack\n"))
    write_review(case)

    assert any("Allowed Source Families" in warning for warning in warnings_of(case))


# --- source-objects.md is parsed as structure ------------------------------------


def test_source_objects_parse_into_locator_and_date() -> None:
    objects, errors = parse_source_objects(
        "# Source Objects\n\n"
        "Intro line.\n\n"
        "- `db.schema.table` weekly counts, wrapped over\n"
        "  two lines (accessed 2026-08-17)\n"
        "- https://example.com/runbook (accessed 2026-08-18)\n"
    )

    assert errors == []
    assert [item.locator for item in objects] == [
        "db.schema.table",
        "https://example.com/runbook",
    ]


@pytest.mark.parametrize(
    "entry",
    [
        "- some long prose about a table, with no locator and no date at all here",
        "- `db.table` with no access date",
        "- `db.table` (accessed 2026-13-99)",
    ],
)
def test_plain_source_object_warns_and_does_not_block(
    tmp_path: Path, entry: str
) -> None:
    case = build_case(tmp_path, source_objects=f"{SOURCE_OBJECTS}{entry}\n")
    write_review(case)

    assert validate_case(case, strict_completion=True) == []
    assert any("source-objects.md" in warning for warning in warnings_of(case))


def test_unlisted_evidence_locator_warns(tmp_path: Path) -> None:
    case = build_case(
        tmp_path,
        source_objects="# Source Objects\n\n- `other.table` (accessed 2026-08-17)\n",
    )
    write_review(case)

    assert any("is not listed" in warning for warning in warnings_of(case))


# --- SQL-backed families need a preserved query --------------------------------


def _with_family(case: Path, family: str, status: str = "used") -> None:
    brief = (case / "brief.md").read_text(encoding="utf-8")
    (case / "brief.md").write_text(
        brief.replace("\nlocal\n", f"\n{family}\n"), encoding="utf-8"
    )
    document = json.loads((case / "evidence.json").read_text(encoding="utf-8"))
    document["coverage"][0]["family"] = family
    document["coverage"][0]["status"] = status
    document["sources"][0]["family"] = family
    (case / "evidence.json").write_text(json.dumps(document), encoding="utf-8")
    write_review(case)


@pytest.mark.parametrize(
    "family", ["snowflake", "bigquery", "postgres", "duckdb", "redshift"]
)
def test_sql_backed_family_used_needs_a_preserved_query(
    tmp_path: Path, family: str
) -> None:
    case = build_case(tmp_path)
    _with_family(case, family)

    errors = validate_case(case, strict_completion=True)

    assert any("no preserved query" in error for error in errors)


def test_sql_backed_family_passes_with_a_query(tmp_path: Path) -> None:
    case = build_case(tmp_path, queries="SELECT count(*) FROM exports;\n")
    _with_family(case, "snowflake")

    assert validate_case(case, strict_completion=True) == []


@pytest.mark.parametrize("family", ["linear", "databricks", "azure"])
def test_other_families_may_state_no_sql(tmp_path: Path, family: str) -> None:
    case = build_case(tmp_path)
    _with_family(case, family)

    assert validate_case(case, strict_completion=True) == []


def test_sql_backed_family_recorded_as_not_used_needs_no_query(tmp_path: Path) -> None:
    case = build_case(
        tmp_path, brief=BRIEF.replace("\nlocal\n", "\nlocal, snowflake\n")
    )
    document = json.loads((case / "evidence.json").read_text(encoding="utf-8"))
    document["coverage"].append(
        {
            "family": "snowflake",
            "status": "not-needed",
            "reason": "The export answers the question.",
            "consequence": "No warehouse cross-check.",
        }
    )
    (case / "evidence.json").write_text(json.dumps(document), encoding="utf-8")
    write_review(case)

    assert validate_case(case, strict_completion=True) == []


# --- Safety is hard. Rigour is a default a person can override. --------------------------


EXPLORATORY_BRIEF = BRIEF.replace(
    "- Research shape: `exploration`",
    "- Research shape: `exploration`\n- Rigour: `exploratory`",
)
EXPLORATORY_REPORT = f"""# Report

{EXPLORATORY_LABEL}

## Executive Summary

Failures rose from 100 to 412 a week in June, after the June 3 scheduler change.
"""


def _exploratory_case(tmp_path: Path, **artifacts: str) -> Path:
    case = tmp_path / "2026-08-17-quick"
    case.mkdir()
    (case / "brief.md").write_text(EXPLORATORY_BRIEF, encoding="utf-8")
    (case / "report.md").write_text(
        artifacts.get("report", EXPLORATORY_REPORT), encoding="utf-8"
    )
    (case / "queries.sql").write_text(artifacts.get("queries", ""), encoding="utf-8")
    return case


def test_exploratory_case_passes_with_only_a_labelled_answer(tmp_path: Path) -> None:
    result = assess_case(_exploratory_case(tmp_path), strict_completion=True)

    assert result.errors == []
    assert result.rigour == "exploratory"
    assert "no independent review" in result.label


def test_exploratory_report_without_its_label_blocks(tmp_path: Path) -> None:
    """A reader who gets only report.md must not mistake it for a reviewed answer."""
    report = EXPLORATORY_REPORT.replace(EXPLORATORY_LABEL, "")
    case = _exploratory_case(tmp_path, report=report)

    assert any(
        "label line" in error for error in validate_case(case, strict_completion=True)
    )


def test_exploratory_wrong_arithmetic_still_blocks(tmp_path: Path) -> None:
    case = fill_case(
        tmp_path / "case", brief=EXPLORATORY_BRIEF, report=REPORT + EXPLORATORY_LABEL
    )
    document = json.loads((case / "evidence.json").read_text(encoding="utf-8"))
    document["calculations"][0]["result"] = "1"
    (case / "evidence.json").write_text(json.dumps(document), encoding="utf-8")

    assert any(
        "does not reconcile" in error
        for error in validate_case(case, strict_completion=True)
    )


@pytest.mark.parametrize("build", [_exploratory_case, build_case])
def test_write_sql_blocks_and_cannot_be_accepted(tmp_path: Path, build) -> None:
    case = build(tmp_path, queries="DROP TABLE t;\n")

    assert accept_findings(case, "I really want this") == []

    assert any("not read-only" in error for error in validate_case(case))
    assert any(
        "not read-only" in error
        for error in validate_case(case, strict_completion=True)
    )
    assert not (case / "overrides.json").exists()


def test_artifact_outside_the_case_blocks_and_cannot_be_accepted(
    tmp_path: Path,
) -> None:
    case = build_case(tmp_path)
    document = json.loads((case / "evidence.json").read_text(encoding="utf-8"))
    document["sources"][0]["artifact"] = "../outside.json"
    (case / "evidence.json").write_text(json.dumps(document), encoding="utf-8")

    accept_findings(case, "accept it")

    assert any(
        "unsafe case artifact" in e for e in validate_case(case, strict_completion=True)
    )


def test_decision_case_without_a_review_blocks_until_accepted(tmp_path: Path) -> None:
    case = build_case(tmp_path)
    (case / "review.json").unlink()
    assert any(
        "independent review is missing" in e
        for e in validate_case(case, strict_completion=True)
    )

    accepted = accept_findings(case, "VP needs it today")

    result = assess_case(case, strict_completion=True)
    assert result.errors == []
    assert any("independent review is missing" in item for item in accepted)
    assert "because VP needs it today" in result.label
    record = json.loads((case / "overrides.json").read_text(encoding="utf-8"))
    assert record["overrides"][0]["reason"] == "VP needs it today"


def test_an_override_does_not_cover_a_new_problem(tmp_path: Path) -> None:
    case = build_case(tmp_path)
    (case / "review.json").unlink()
    accept_findings(case, "VP needs it today")
    (case / "report.md").write_text("# Empty\n", encoding="utf-8")

    assert any(
        "Executive Summary" in e for e in validate_case(case, strict_completion=True)
    )


def test_blank_override_reason_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="reason"):
        accept_findings(build_case(tmp_path), "  ")


def test_stale_review_warns_and_is_labelled_unless_pinned(tmp_path: Path) -> None:
    case = build_case(tmp_path)
    with (case / "report.md").open("a", encoding="utf-8") as handle:
        handle.write("\nA small edit.\n")

    result = assess_case(case, strict_completion=True)
    assert result.errors == []
    assert any("stale for report.md" in warning for warning in result.warnings)
    assert "predates the latest edits" in result.label

    pinned = assess_case(case, strict_completion=True, pinned=True)
    assert any("stale for report.md" in error for error in pinned.errors)


def test_blocked_review_verdict_blocks_a_decision_case(tmp_path: Path) -> None:
    case = build_case(tmp_path)
    write_review(case, verdict="blocked")

    assert any(
        "verdict is blocked" in e for e in validate_case(case, strict_completion=True)
    )
