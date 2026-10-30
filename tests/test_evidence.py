from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from support.checks import validate_evidence

from fact_finder.evidence import (
    SCAFFOLD_COVERAGE_REASON,
    Evidence,
    evidence_template,
    review_snapshot,
)


def _write_evidence(case: Path, evidence: dict[str, Any]) -> None:
    (case / "evidence.json").write_text(json.dumps(evidence), encoding="utf-8")


def _complete_case(case: Path) -> dict[str, Any]:
    for name in ("brief.md", "source-objects.md"):
        (case / name).write_text(f"Preserved {name}\n", encoding="utf-8")
    (case / "queries.sql").write_text("-- query_id: 01b-query-id\nSELECT 1;\n", encoding="utf-8")
    (case / "report.md").write_text("Registrations rose by 20. [C1]\n", encoding="utf-8")
    artifact = b'{"June":100,"July":120}\n'
    (case / "monthly.json").write_bytes(artifact)
    evidence = {
        "schema_version": 1,
        "sources": [
            {
                "id": "S1",
                "family": "warehouse",
                "route": "warehouse.execute_sql",
                "locator": "ANALYTICS.PUBLIC.REGISTRATIONS",
                "accessed_at": "2026-10-17T11:00:00Z",
                "independence_group": "warehouse-registration-model",
                "artifact": "monthly.json",
                "sha256": hashlib.sha256(artifact).hexdigest(),
                "query_id": "01b-query-id",
            }
        ],
        "coverage": [
            {
                "family": "warehouse",
                "status": "used",
                "reason": "Warehouse counts answer the monthly comparison.",
                "consequence": "Counts depend on warehouse completeness.",
            }
        ],
        "claims": [
            {
                "id": "C1",
                "statement": "Registrations rose by 20.",
                "kind": "descriptive",
                "source_ids": ["S1"],
                "calculation_ids": ["D1"],
                "limitations": ["Counts may change after late events."],
                "status": "supported",
                "report_marker": "[C1]",
            }
        ],
        "calculations": [
            {
                "id": "D1",
                "operation": "difference",
                "inputs": [
                    {
                        "name": "July",
                        "value": "120",
                        "unit": "users",
                        "source_id": "S1",
                    },
                    {
                        "name": "June",
                        "value": "100",
                        "unit": "users",
                        "source_id": "S1",
                    },
                ],
                "result": "20",
                "unit": "users",
                "tolerance": "0",
            }
        ],
    }
    _write_evidence(case, evidence)
    _write_review(case)
    return evidence


def _write_review(case: Path, **overrides: object) -> dict[str, Any]:
    review: dict[str, Any] = {
        "schema_version": 1,
        "reviewer": "independent-challenger-17",
        "reviewed_hashes": review_snapshot(case),
        "objections": [
            {
                "objection": "Month length could explain the count increase.",
                "disposition": "narrowed",
                "resolution": "The claim describes counts and makes no causal inference.",
            }
        ],
        "strongest_alternative": "Late ingestion could change warehouse counts.",
        "weakest_claim": "C1 depends on complete monthly data.",
        "fragile_dependency": "The registration warehouse model.",
        "verdict": "pass",
    }
    review.update(overrides)
    (case / "review.json").write_text(json.dumps(review), encoding="utf-8")
    return review


def test_complete_evidence_and_independent_snapshot_pass(tmp_path: Path) -> None:
    _complete_case(tmp_path)

    assert validate_evidence(tmp_path, strict_completion=True) == []
    assert "monthly.json" in review_snapshot(tmp_path)


def test_empty_template_is_not_a_completed_case(tmp_path: Path) -> None:
    (tmp_path / "evidence.json").write_text(
        evidence_template(["warehouse", "notion"]), encoding="utf-8"
    )

    assert validate_evidence(tmp_path) == []
    errors = validate_evidence(tmp_path, strict_completion=True)
    assert any("no preserved source and claim yet" in error for error in errors)
    assert any("independent review is missing" in error for error in errors)


def test_case_without_evidence_cannot_complete(tmp_path: Path) -> None:
    assert validate_evidence(tmp_path) == []
    assert validate_evidence(tmp_path, strict_completion=True) == [
        "evidence.json: the evidence manifest is missing. Fix: see "
        "`research schema evidence`, or create the case with `--rigour decision`."
    ]


def test_claim_must_cite_a_source(tmp_path: Path) -> None:
    evidence = _complete_case(tmp_path)
    evidence["claims"][0]["source_ids"] = []
    _write_evidence(tmp_path, evidence)

    assert "source_ids" in validate_evidence(tmp_path)[0]


def test_scaffold_coverage_text_fails_strict(tmp_path: Path) -> None:
    evidence = _complete_case(tmp_path)
    evidence["coverage"][0]["reason"] = SCAFFOLD_COVERAGE_REASON
    _write_evidence(tmp_path, evidence)
    _write_review(tmp_path)

    assert any(
        "still the scaffold text" in error
        for error in validate_evidence(tmp_path, strict_completion=True)
    )


def test_deeply_nested_evidence_is_a_clean_error(tmp_path: Path) -> None:
    (tmp_path / "evidence.json").write_text("[" * 1_000_000, encoding="utf-8")

    assert "nested too deeply" in validate_evidence(tmp_path)[0]


def test_source_query_id_must_exist_in_queries_sql(tmp_path: Path) -> None:
    _complete_case(tmp_path)
    (tmp_path / "queries.sql").write_text("SELECT 1;\n", encoding="utf-8")
    _write_review(tmp_path)

    assert any(
        "query_id 01b-query-id" in error
        for error in validate_evidence(tmp_path, strict_completion=True)
    )


@pytest.mark.parametrize(
    "reviewer",
    [
        "claude",
        "Claude Code",
        "Claude Opus",
        "codex",
        "main agent",
        "the agent",
        "reviewer",
        "me",
        "self",
        "TBD",
        "subagent",
    ],
)
def test_review_rejects_self_review_and_bare_client_names(tmp_path: Path, reviewer: str) -> None:
    _complete_case(tmp_path)
    _write_review(tmp_path, reviewer=reviewer)

    assert any(
        "names no independent reviewer" in error
        for error in validate_evidence(tmp_path, strict_completion=True)
    )


@pytest.mark.parametrize(
    "reviewer",
    [
        "independent-subagent-challenger",
        "claude-subagent-a4f21",
        "Task(reviewer-a4f21)",
    ],
)
def test_review_accepts_a_specific_reviewer_identity(tmp_path: Path, reviewer: str) -> None:
    _complete_case(tmp_path)
    _write_review(tmp_path, reviewer=reviewer)

    assert validate_evidence(tmp_path, strict_completion=True) == []


@pytest.mark.parametrize(
    "changed",
    [
        "report.md",
        "brief.md",
        "queries.sql",
        "source-objects.md",
        "evidence.json",
        "monthly.json",
    ],
)
def test_review_is_invalidated_by_any_reviewed_input_change(tmp_path: Path, changed: str) -> None:
    _complete_case(tmp_path)
    with (tmp_path / changed).open("a", encoding="utf-8") as handle:
        handle.write("\n")

    errors = validate_evidence(tmp_path, strict_completion=True)

    assert any(f"stale for {changed}" in error for error in errors)
    if changed == "monthly.json":
        assert any("sha256 does not match" in error for error in errors)


def test_snapshot_cannot_fabricate_an_approval(tmp_path: Path) -> None:
    _complete_case(tmp_path)
    (tmp_path / "review.json").unlink()

    assert review_snapshot(tmp_path)
    assert not (tmp_path / "review.json").exists()
    assert any(
        "independent review is missing" in e
        for e in validate_evidence(tmp_path, strict_completion=True)
    )


@pytest.mark.parametrize(
    "path",
    [
        "../outside.json",
        "/tmp/outside.json",
        "nested/../../outside.json",
        "./monthly.json",
        r"..\outside.json",
    ],
)
def test_artifact_path_must_stay_in_case(tmp_path: Path, path: str) -> None:
    evidence = _complete_case(tmp_path)
    evidence["sources"][0]["artifact"] = path
    _write_evidence(tmp_path, evidence)

    assert any("unsafe case artifact path" in error for error in validate_evidence(tmp_path))


def test_source_symlink_cannot_escape_case(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    evidence = _complete_case(case)
    outside = tmp_path / "outside.json"
    outside.write_text("secret", encoding="utf-8")
    (case / "linked.json").symlink_to(outside)
    evidence["sources"][0]["artifact"] = "linked.json"
    _write_evidence(case, evidence)

    assert any("escapes the case directory" in error for error in validate_evidence(case))


@pytest.mark.parametrize("collection", ["sources", "claims", "calculations", "coverage"])
def test_duplicate_identifiers_are_rejected(tmp_path: Path, collection: str) -> None:
    evidence = _complete_case(tmp_path)
    evidence[collection].append(evidence[collection][0])
    _write_evidence(tmp_path, evidence)

    assert "more than once" in validate_evidence(tmp_path)[0]


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", True])
@pytest.mark.parametrize("field", ["result", "tolerance", "input"])
def test_nonfinite_or_boolean_arithmetic_is_rejected(
    tmp_path: Path, value: object, field: str
) -> None:
    evidence = _complete_case(tmp_path)
    calculation = evidence["calculations"][0]
    if field == "input":
        calculation["inputs"][0]["value"] = value
    else:
        calculation[field] = value
    _write_evidence(tmp_path, evidence)

    assert "evidence.json" in validate_evidence(tmp_path)[0]


@pytest.mark.parametrize(
    "operation,result,unit,denominator",
    [
        ("sum", "220", "users", None),
        ("difference", "20", "users", None),
        ("ratio", "1.2", "ratio", "June"),
    ],
)
def test_supported_operations_reconcile(
    tmp_path: Path, operation: str, result: str, unit: str, denominator: str | None
) -> None:
    evidence = _complete_case(tmp_path)
    evidence["calculations"][0].update(
        operation=operation, result=result, unit=unit, denominator=denominator
    )
    _write_evidence(tmp_path, evidence)
    _write_review(tmp_path)

    assert validate_evidence(tmp_path, strict_completion=True) == []


def test_arithmetic_mismatch_fails_even_when_review_passes(tmp_path: Path) -> None:
    evidence = _complete_case(tmp_path)
    evidence["calculations"][0]["result"] = "-20"
    _write_evidence(tmp_path, evidence)
    _write_review(tmp_path)

    assert any("calculation D1 result" in e for e in validate_evidence(tmp_path))


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("zero", "ratio denominator is zero"),
        ("missing", "named denominator"),
        ("negative-tolerance", "greater than or equal to 0"),
        ("units", "different units"),
    ],
)
def test_invalid_calculation_contract_is_rejected(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    evidence = _complete_case(tmp_path)
    calculation = evidence["calculations"][0]
    if mutation in {"zero", "missing"}:
        calculation.update(operation="ratio", result="1.2", unit="ratio")
        if mutation == "zero":
            calculation["denominator"] = "June"
            calculation["inputs"][1]["value"] = "0"
    elif mutation == "negative-tolerance":
        calculation["tolerance"] = "-1"
    else:
        calculation["inputs"][1]["unit"] = "sessions"
    _write_evidence(tmp_path, evidence)

    assert expected in validate_evidence(tmp_path)[0]


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("claim-source", "cites S2, but only S1 is declared"),
        ("input-source", "uses S2, but only S1 is declared"),
        ("calculation", "cites D2, but only D1 is declared"),
        ("coverage", "but coverage does not mark it used"),
        ("marker", "report_marker is [C2]"),
        ("extra", "is not a known field"),
        ("time", "time zone"),
    ],
)
def test_manifest_rejects_broken_references_and_malformed_fields(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    evidence = _complete_case(tmp_path)
    if mutation == "claim-source":
        evidence["claims"][0]["source_ids"] = ["S2"]
    elif mutation == "input-source":
        evidence["calculations"][0]["inputs"][0]["source_id"] = "S2"
    elif mutation == "calculation":
        evidence["claims"][0]["calculation_ids"] = ["D2"]
    elif mutation == "coverage":
        evidence["coverage"][0]["status"] = "unavailable"
    elif mutation == "marker":
        evidence["claims"][0]["report_marker"] = "[C2]"
    elif mutation == "time":
        evidence["sources"][0]["accessed_at"] = "2026-10-17T11:00:00"
    else:
        evidence["claims"][0]["invented"] = True
    _write_evidence(tmp_path, evidence)

    assert expected in validate_evidence(tmp_path)[0]


def test_report_markers_must_match_registered_claims(tmp_path: Path) -> None:
    _complete_case(tmp_path)
    (tmp_path / "report.md").write_text("An unknown claim. [C2]\n", encoding="utf-8")
    _write_review(tmp_path)

    errors = validate_evidence(tmp_path, strict_completion=True)

    assert any("marker [C2] names no claim" in error for error in errors)
    assert any("claim marker [C1] is missing" in error for error in errors)


def test_review_with_blocking_objection_cannot_pass(tmp_path: Path) -> None:
    _complete_case(tmp_path)
    _write_review(
        tmp_path,
        objections=[
            {
                "objection": "Wrong cohort.",
                "disposition": "blocking",
                "resolution": "Recompute.",
            }
        ],
    )

    assert "verdict is pass with a blocking objection" in validate_evidence(tmp_path)[0]


def test_blocked_review_prevents_strict_completion(tmp_path: Path) -> None:
    _complete_case(tmp_path)
    _write_review(tmp_path, verdict="blocked")

    assert any(
        "review.json: verdict is blocked" in error
        for error in validate_evidence(tmp_path, strict_completion=True)
    )


def test_review_must_include_source_artifact_hashes(tmp_path: Path) -> None:
    _complete_case(tmp_path)
    hashes = review_snapshot(tmp_path)
    del hashes["monthly.json"]
    _write_review(tmp_path, reviewed_hashes=hashes)

    assert any("exactly the review inputs" in error for error in validate_evidence(tmp_path))


def test_json_schema_is_available_for_authors() -> None:
    assert Evidence.model_json_schema()["additionalProperties"] is False


@pytest.mark.parametrize("field,value", [("kind", "causal"), ("status", "inconclusive")])
def test_uncertain_claims_require_limitations(tmp_path: Path, field: str, value: str) -> None:
    evidence = _complete_case(tmp_path)
    evidence["claims"][0].update({field: value, "limitations": []})
    _write_evidence(tmp_path, evidence)

    assert "with no limitations" in validate_evidence(tmp_path)[0]


def test_decimal_overflow_is_a_validation_error(tmp_path: Path) -> None:
    evidence = _complete_case(tmp_path)
    calculation = evidence["calculations"][0]
    calculation.update(operation="ratio", denominator="June", unit="ratio", result="1e999999")
    calculation["inputs"][0]["value"] = "1e999999"
    calculation["inputs"][1]["value"] = "0.01"
    _write_evidence(tmp_path, evidence)

    assert any("could not be evaluated" in error for error in validate_evidence(tmp_path))


def test_decimal_sum_preserves_precision_beyond_default_context(tmp_path: Path) -> None:
    evidence = _complete_case(tmp_path)
    calculation = evidence["calculations"][0]
    calculation.update(operation="sum", result="12345678901234567890123456790")
    calculation["inputs"][0]["value"] = "12345678901234567890123456789"
    calculation["inputs"][1]["value"] = "1"
    _write_evidence(tmp_path, evidence)
    _write_review(tmp_path)

    assert validate_evidence(tmp_path, strict_completion=True) == []


def test_template_is_valid_json_with_trailing_newline() -> None:
    template = evidence_template(["warehouse"])

    assert template.endswith("\n")
    assert json.loads(template)["schema_version"] == 1


def test_json_decimal_tokens_preserve_exact_arithmetic(tmp_path: Path) -> None:
    evidence = _complete_case(tmp_path)
    calculation = evidence["calculations"][0]
    calculation["inputs"][0]["value"] = "EXACT_HIGH"
    calculation["inputs"][1]["value"] = "EXACT_LOW"
    calculation["result"] = "0"
    text = (
        json.dumps(evidence)
        .replace('"EXACT_HIGH"', "9007199254740993.0")
        .replace('"EXACT_LOW"', "9007199254740992.0")
    )
    (tmp_path / "evidence.json").write_text(text)
    _write_review(tmp_path)
    assert any(
        "does not reconcile" in error
        for error in validate_evidence(tmp_path, strict_completion=True)
    )


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    _complete_case(tmp_path)
    path = tmp_path / "evidence.json"
    path.write_text(
        path.read_text().replace('"schema_version": 1', '"schema_version": 2, "schema_version": 1')
    )
    assert any("duplicate JSON key" in error for error in validate_evidence(tmp_path))
