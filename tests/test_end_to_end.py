"""Drive the real commands offline, the way a goal does."""

from __future__ import annotations

import json
from pathlib import Path

from support.cases import fill_case, fill_with_lorem_ipsum, review_document

from agentic_research_loop.cli import main


def test_case_lifecycle(repo_root: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)

    assert (
        main(
            [
                "init",
                "exports",
                "--question",
                "Why did failures rise?",
                "--local-only",
                "--rigour",
                "decision",
            ]
        )
        == 0
    )
    case = next((repo_root / "research").iterdir())

    assert main(["goal", case.name]) == 0
    assert capsys.readouterr().out.count(f'validate "{case}" --strict') == 1

    assert main(["validate", case.name]) == 0
    capsys.readouterr()
    assert main(["validate", case.name, "--strict"]) == 1
    empty_failures = capsys.readouterr().out
    assert "Executive Summary" in empty_failures
    assert "independent review is missing" in empty_failures

    fill_case(case)
    assert main(["validate", case.name, "--strict"]) == 0
    assert "cannot be proved by a gate" in capsys.readouterr().out

    with (case / "report.md").open("a", encoding="utf-8") as report:
        report.write("\nA late edit the reviewer never saw.\n")
    assert main(["validate", case.name, "--strict"]) == 0
    assert "review.json is stale for report.md" in capsys.readouterr().out
    assert main(["validate", case.name, "--strict", "--pinned"]) == 1
    assert "review.json is stale for report.md" in capsys.readouterr().out


def test_lorem_ipsum_with_reviewer_claude_fails_strict(
    repo_root: Path, monkeypatch, capsys
) -> None:
    """This exact filler passed the notes.md gate. evidence.json and review.json own it now."""
    monkeypatch.chdir(repo_root)
    main(["init", "filler", "--local-only", "--rigour", "decision"])
    case = next((repo_root / "research").iterdir())
    fill_with_lorem_ipsum(case)
    capsys.readouterr()

    assert main(["validate", case.name, "--strict"]) == 1

    output = capsys.readouterr().out
    assert "no preserved source and claim yet" in output
    assert "independent review is missing" in output
    assert "has no locator or access date" in output


def test_reviewer_claude_fails_even_with_a_consistent_manifest(
    repo_root: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(repo_root)
    case = fill_case(repo_root / "research" / "2026-08-17-filled")
    (case / "review.json").write_text(
        json.dumps(review_document(case, reviewer="claude")), encoding="utf-8"
    )

    assert main(["validate", case.name, "--strict"]) == 1

    assert "names no independent reviewer" in capsys.readouterr().out
