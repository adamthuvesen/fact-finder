"""A result states what actually happened, and safety holds whatever else is wrong."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from support.cases import fill_case, write_review

from fact_finder.cli import main


def _init(repo_root: Path, *extra: str) -> Path:
    assert main(["init", "case", "--question", "Why?", "--local-only", *extra]) == 0
    return next((repo_root / "research").iterdir())


def _answer(case: Path) -> None:
    report = case / "report.md"
    report.write_text(
        report.read_text(encoding="utf-8").replace(
            "<!-- research:placeholder --> Complete this section with the answer and the most "
            "decision-relevant evidence.",
            "Yes. Failures rose from 100 to 412 a week after the June scheduler change.",
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def repo(repo_root, monkeypatch):
    monkeypatch.chdir(repo_root)
    return repo_root


def _json(capsys, *args: str) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = main(["validate", *args, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_undecodable_queries_fail_closed_and_cannot_be_accepted(repo, capsys) -> None:
    case = _init(repo)
    _answer(case)
    (case / "queries.sql").write_bytes(b"DELETE FROM users; -- caf\xe9\n")
    capsys.readouterr()

    assert main(["validate", case.name]) == 1
    assert main(["validate", case.name, "--strict", "--accept", "fine"]) == 1
    assert "queries.sql: could not read" in capsys.readouterr().out
    assert not (case / "overrides.json").exists()
    assert main(["list"]) == 0
    assert "invalid" in capsys.readouterr().out


@pytest.mark.parametrize("rigour", ["exploratory", "decision"])
def test_unreadable_queries_fail_closed(repo, rigour) -> None:
    case = _init(repo, "--rigour", rigour)
    _answer(case)
    path = case / "queries.sql"
    path.chmod(0)
    try:
        assert main(["validate", case.name, "--strict", "--accept", "fine"]) == 1
    finally:
        path.chmod(0o644)


def test_accepting_a_scaffold_names_every_gap_and_never_says_checked(repo, capsys) -> None:
    case = _init(repo, "--rigour", "decision")

    code, payload = _json(capsys, case.name, "--strict", "--accept", "x")

    assert code == 0
    assert "evidence checked" not in payload["label"]
    assert "not fully checked" in payload["label"]
    assert "independent review is missing" in payload["label"]
    assert "because x" in payload["label"]


def test_pinned_accept_on_a_stale_review_is_not_called_fresh(repo, capsys) -> None:
    case = fill_case(repo / "research" / "2026-08-17-filled")
    with (case / "report.md").open("a", encoding="utf-8") as handle:
        handle.write("\nA late edit.\n")

    code, payload = _json(capsys, case.name, "--strict", "--pinned", "--accept", "small typo")

    assert code == 0
    assert "fresh" not in payload["label"]
    assert "stale for report.md" in payload["label"]


def test_a_failed_run_is_labelled_as_failed(repo, capsys) -> None:
    case = _init(repo, "--rigour", "decision")

    code, payload = _json(capsys, case.name, "--strict")

    assert code == 1
    assert payload["label"].startswith("Not complete")


def test_outside_artifact_with_a_schema_error_stays_hard(repo, capsys) -> None:
    case = fill_case(repo / "research" / "2026-08-17-filled")
    document = json.loads((case / "evidence.json").read_text(encoding="utf-8"))
    document["sources"][0]["artifact"] = "../../outside.json"
    document["unexpected"] = 1
    (case / "evidence.json").write_text(json.dumps(document), encoding="utf-8")

    code, payload = _json(capsys, case.name, "--strict", "--accept", "fine")

    assert code == 1
    assert any("unsafe case artifact path" in error for error in payload["errors"])


def test_stale_review_shows_in_list(repo, capsys) -> None:
    case = fill_case(repo / "research" / "2026-08-17-filled")
    with (case / "report.md").open("a", encoding="utf-8") as handle:
        handle.write("\nA late edit.\n")
    capsys.readouterr()

    assert main(["list"]) == 0

    assert "decision-stale-review" in capsys.readouterr().out


def test_report_carries_each_accepted_gap(repo, capsys) -> None:
    case = _init(repo)
    _answer(case)
    report = case / "report.md"
    report.write_text(
        report.read_text(encoding="utf-8").replace(
            "Exploratory answer: not independently reviewed.\n", ""
        ),
        encoding="utf-8",
    )

    assert main(["validate", case.name, "--strict", "--accept", "shared by hand"]) == 0

    text = report.read_text(encoding="utf-8")
    assert "## Accepted Gaps" in text
    assert "exploratory label line is missing" in text
    assert "shared by hand" in text
    assert "exploratory label line is missing" in capsys.readouterr().out


def test_accepting_does_not_make_a_review_stale(repo, capsys) -> None:
    case = fill_case(repo / "research" / "2026-08-17-filled")
    write_review(case, verdict="blocked")

    assert main(["validate", case.name, "--strict", "--accept", "known"]) == 0
    capsys.readouterr()

    assert main(["validate", case.name, "--strict", "--pinned"]) == 0
    assert "stale" not in capsys.readouterr().out


def test_a_repeat_accept_records_the_new_reason(repo, capsys) -> None:
    case = _init(repo, "--rigour", "decision")
    main(["validate", case.name, "--strict", "--accept", "first"])

    code, payload = _json(capsys, case.name, "--strict", "--accept", "second")

    assert code == 0
    assert "first; second" in payload["label"]
    record = json.loads((case / "overrides.json").read_text(encoding="utf-8"))
    assert [item["reason"] for item in record["overrides"]] == ["first", "second"]
    report = (case / "report.md").read_text(encoding="utf-8")
    assert report.count("## Accepted Gaps") == 1
    assert "second" in report


def test_exploratory_blocked_verdict_warns(repo, capsys) -> None:
    case = _init(repo)
    _answer(case)
    (case / "review.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "reviewer": "task-reviewer-a4f21",
                "reviewed_hashes": dict.fromkeys(
                    (
                        "brief.md",
                        "report.md",
                        "queries.sql",
                        "source-objects.md",
                        "evidence.json",
                    ),
                    "0" * 64,
                ),
                "objections": [],
                "strongest_alternative": "x",
                "weakest_claim": "x",
                "fragile_dependency": "x",
                "verdict": "blocked",
            }
        ),
        encoding="utf-8",
    )

    code, payload = _json(capsys, case.name, "--strict")

    assert code == 0
    assert any("verdict is blocked" in item for item in payload["warnings"])


def test_a_quick_case_collapses_unfilled_sections(repo, capsys) -> None:
    case = _init(repo)
    _answer(case)

    _, payload = _json(capsys, case.name, "--strict")

    unfilled = [w for w in payload["warnings"] if "unfilled sections" in w]
    assert len(unfilled) == 1
    assert "Evidence" in unfilled[0]
    assert len(payload["warnings"]) <= 3
    assert not any("placeholder under" in w for w in payload["warnings"])


def _complete(repo_root: Path) -> Path:
    case = repo_root / "research" / "2026-01-01-case"
    fill_case(case)
    return case


def test_an_unreadable_query_file_in_a_decision_case_names_file_and_fix(repo, capsys) -> None:
    case = _complete(repo)
    (case / "queries.sql").write_bytes(b"SELECT '\xe9';\n")

    assert main(["validate", case.name, "--strict"]) == 1

    out = capsys.readouterr().out
    assert "queries.sql: could not read" in out
    assert "Fix: save it as UTF-8" in out
    assert "\ncodec" not in out


def test_removing_a_hash_from_a_stale_review_cannot_end_up_fresh(repo, capsys) -> None:
    case = _complete(repo)
    with (case / "report.md").open("a", encoding="utf-8") as handle:
        handle.write("\nA late edit.\n")
    review = json.loads((case / "review.json").read_text(encoding="utf-8"))
    del review["reviewed_hashes"]["report.md"]
    (case / "review.json").write_text(json.dumps(review), encoding="utf-8")
    capsys.readouterr()

    assert main(["validate", case.name, "--strict", "--pinned"]) == 1

    out = capsys.readouterr().out
    assert "review fresh" not in out
    assert "copy" not in out.lower()
    assert "Fix: ask a new independent reviewer" in out
    assert f"research review-snapshot {case.name}" in out


def test_a_stale_review_fix_names_the_changed_file_and_exact_command(repo, capsys) -> None:
    case = _complete(repo)
    with (case / "report.md").open("a", encoding="utf-8") as handle:
        handle.write("\nA late edit.\n")
    capsys.readouterr()

    assert main(["validate", case.name, "--strict", "--pinned"]) == 1

    out = capsys.readouterr().out
    assert "stale for report.md" in out
    assert "re-check report.md" in out
    assert f"research review-snapshot {case.name}" in out


def test_an_extra_hash_is_stale_and_never_labelled_fresh(repo, capsys) -> None:
    case = _complete(repo)
    review = json.loads((case / "review.json").read_text(encoding="utf-8"))
    review["reviewed_hashes"]["gone.json"] = "0" * 64
    (case / "review.json").write_text(json.dumps(review), encoding="utf-8")
    capsys.readouterr()

    assert main(["validate", case.name, "--strict", "--json"]) == 0

    assert "fresh" not in json.loads(capsys.readouterr().out)["label"]
