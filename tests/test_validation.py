from __future__ import annotations

import json
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

from agentic_research_loop.templates import (
    PLACEHOLDER,
    notes_template,
    queries_template,
    report_template,
    source_objects_template,
)
from agentic_research_loop.validation import parse_source_objects, validate_case


def build_case(tmp_path: Path, **artifacts: str) -> Path:
    return fill_case(tmp_path / "2026-08-17-exports", **artifacts)


def test_complete_case_passes_strict(tmp_path: Path) -> None:
    assert validate_case(build_case(tmp_path), strict_completion=True) == []


def test_missing_artifact_is_reported(tmp_path: Path) -> None:
    case = build_case(tmp_path)
    (case / "source-objects.md").unlink()

    assert "Missing required file: source-objects.md" in validate_case(case)


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


def test_strict_requires_preserved_sql_or_a_stated_reason(tmp_path: Path) -> None:
    case = build_case(tmp_path, queries="-- nothing preserved here\n")

    errors = validate_case(case, strict_completion=True)

    assert any("No SQL used" in error for error in errors)


def test_strict_rejects_a_placeholder_question(tmp_path: Path) -> None:
    case = build_case(tmp_path, brief=BRIEF.replace(QUESTION, "Research: exports"))

    errors = validate_case(case, strict_completion=True)

    assert any("specific research question" in error for error in errors)


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


def test_root_cause_brief_needs_its_design_sections(tmp_path: Path) -> None:
    case = build_case(tmp_path, brief=BRIEF.replace("`exploration`", "`root-cause`"))

    errors = validate_case(case)

    assert any("Hypotheses" in error for error in errors)
    assert any("Known Confounders" in error for error in errors)
    assert any("Required Cross-Checks" in error for error in errors)


def test_high_priority_thread_needs_a_discriminating_test(tmp_path: Path) -> None:
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

    errors = validate_case(case)

    assert any("Discriminating Test" in error for error in errors)


def test_committed_demo_case_passes_strict_validation() -> None:
    """The shipped example is the reference output shape; it has to clear the gate."""
    demo = Path(__file__).resolve().parents[1] / "examples" / "demo-export-reliability"

    assert validate_case(demo, strict_completion=True) == []


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
    assert any("source-objects.md" in error for error in errors)
    assert any("No SQL used" in error for error in errors)


def test_an_unreadable_research_shape_is_an_error_not_a_silent_skip(
    tmp_path: Path,
) -> None:
    case = build_case(
        tmp_path,
        brief=BRIEF.replace(
            "- Research shape: `exploration`", "- Research shape: `bogus`"
        ),
    )

    assert any("unknown research shape" in error for error in validate_case(case))


def test_missing_research_shape_is_reported(tmp_path: Path) -> None:
    case = build_case(
        tmp_path, brief=BRIEF.replace("- Research shape: `exploration`\n", "")
    )

    assert any("Research shape" in error for error in validate_case(case))


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

    assert any("Hypotheses" in error for error in validate_case(case))


def test_select_into_is_rejected(tmp_path: Path) -> None:
    case = build_case(
        tmp_path, queries="SELECT week INTO exports_snapshot FROM exports;\n"
    )

    assert any("INTO" in error for error in validate_case(case))


def test_coverage_must_match_the_allowed_families(tmp_path: Path) -> None:
    case = build_case(tmp_path, brief=BRIEF.replace("\nlocal\n", "\nlocal, slack\n"))

    assert any(
        "Allowed Source Families" in error
        for error in validate_case(case, strict_completion=True)
    )


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
def test_malformed_source_object_fails(tmp_path: Path, entry: str) -> None:
    case = build_case(tmp_path, source_objects=f"{SOURCE_OBJECTS}{entry}\n")
    write_review(case)

    assert any(
        "source-objects.md" in error
        for error in validate_case(case, strict_completion=True)
    )


def test_evidence_locator_must_be_listed_in_source_objects(tmp_path: Path) -> None:
    case = build_case(
        tmp_path,
        source_objects="# Source Objects\n\n- `other.table` (accessed 2026-08-17)\n",
    )

    assert any(
        "is not listed in source-objects.md" in error
        for error in validate_case(case, strict_completion=True)
    )


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

    assert any("needs a preserved read-only query" in error for error in errors)


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
