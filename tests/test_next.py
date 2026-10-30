"""`research next` reads case state and names one next step with its exact command."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
from support.cases import fill_case, fill_with_lorem_ipsum

from fact_finder.cli import main


@pytest.fixture(autouse=True)
def _in_repo(repo_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(repo_root)


def _next(capsys, *args: str) -> str:
    capsys.readouterr()
    assert main(["next", *args]) == 0
    return capsys.readouterr().out


def _init(repo_root: Path, slug: str, *flags: str) -> Path:
    assert main(["init", slug, "--local-only", "--question", "Why?", *flags]) == 0
    return next((repo_root / "research").glob(f"*-{slug}"))


def test_no_case_points_at_init(capsys) -> None:
    assert "uv run research init <slug>" in _next(capsys)


def test_a_new_case_points_at_its_goal(repo_root: Path, capsys) -> None:
    case = _init(repo_root, "fresh")

    out = _next(capsys, case.name)

    assert f'uv run research goal "{case}"' in out


def test_no_argument_picks_the_open_case(repo_root: Path, capsys) -> None:
    case = _init(repo_root, "fresh")

    assert case.name in _next(capsys)


def test_a_decision_case_with_no_review_points_at_the_snapshot(repo_root: Path, capsys) -> None:
    case = repo_root / "research" / "2026-01-01-case"
    case.mkdir(parents=True)
    fill_case(case)
    (case / "review.json").unlink()

    out = _next(capsys, case.name)

    assert f'uv run research review-snapshot "{case}"' in out


def test_a_write_query_comes_first(repo_root: Path, capsys) -> None:
    case = _init(repo_root, "fresh")
    (case / "queries.sql").write_text("DROP TABLE t;\n", encoding="utf-8")

    out = _next(capsys, case.name)

    assert "queries.sql:1: not read-only" in out
    assert "--strict" in out


def test_a_blocked_case_shows_the_first_fix_and_the_count(repo_root: Path, capsys) -> None:
    case = repo_root / "research" / "2026-01-01-case"
    case.mkdir(parents=True)
    fill_with_lorem_ipsum(case)

    out = _next(capsys, case.name)

    assert "Fix:" in out
    assert "blocking findings remain" in out
    assert f'validate "{case}" --strict' in out


def test_a_complete_decision_case_needs_nothing(repo_root: Path, capsys) -> None:
    case = repo_root / "research" / "2026-01-01-case"
    case.mkdir(parents=True)
    fill_case(case)

    assert "Nothing blocks completion." in _next(capsys, case.name)


def test_a_stale_review_asks_for_a_new_one_and_never_a_new_hash(repo_root: Path, capsys) -> None:
    case = repo_root / "research" / "2026-01-01-case"
    case.mkdir(parents=True)
    fill_case(case)
    with (case / "report.md").open("a", encoding="utf-8") as handle:
        handle.write("\nA late edit.\n")

    out = _next(capsys, case.name)

    assert "new independent reviewer" in out


def test_an_exploratory_answer_offers_the_decision_path(repo_root: Path, capsys) -> None:
    case = _init(repo_root, "fresh")
    report = (case / "report.md").read_text(encoding="utf-8")
    (case / "report.md").write_text(
        report.replace(
            "<!-- research:placeholder -->",
            "Failures rose from 100 to 412 after the deploy, and the deploy explains it.",
            1,
        ),
        encoding="utf-8",
    )

    assert "--rigour decision" in _next(capsys, case.name)


def test_next_is_advice_and_writes_nothing(repo_root: Path, capsys) -> None:
    case = _init(repo_root, "fresh")
    before = {path: path.read_bytes() for path in case.iterdir()}

    _next(capsys, case.name)

    assert {path: path.read_bytes() for path in case.iterdir()} == before


def test_the_goal_contract_points_at_next(repo_root: Path, capsys) -> None:
    case = _init(repo_root, "fresh")
    capsys.readouterr()

    assert main(["goal", case.name]) == 0

    assert f'research next "{case}"' in capsys.readouterr().out


def test_the_decision_command_can_be_pasted_as_is(repo_root: Path, capsys) -> None:
    context = repo_root / "context"
    context.mkdir()
    assert (
        main(
            [
                "init",
                "churn-check",
                "--sources",
                "web-search",
                "--context-path",
                str(context),
                "--question",
                "Did churn rise in June?",
            ]
        )
        == 0
    )
    case = next((repo_root / "research").glob("*-churn-check"))
    report = case / "report.md"
    report.write_text(
        report.read_text(encoding="utf-8").replace(
            "<!-- research:placeholder -->",
            "Churn rose from 2 to 3 percent in June, and pricing explains most of it.",
            1,
        ),
        encoding="utf-8",
    )

    line = next(
        entry for entry in _next(capsys, case.name).splitlines() if "--rigour decision" in entry
    )
    command = shlex.split(line.split("run: ", 1)[1])

    assert command[:3] == ["uv", "run", "research"]
    assert "<" not in line
    capsys.readouterr()
    assert main(command[3:]) == 0
    copies = [path for path in (repo_root / "research").iterdir() if path != case]
    assert len(copies) == 1
    assert copies[0].name.endswith("churn-check-decision")
    assert len(re.findall(r"\d{4}-\d{2}-\d{2}", copies[0].name)) == 1
    brief = (copies[0] / "brief.md").read_text(encoding="utf-8")
    assert "Did churn rise in June?" in brief
    assert "web-search, local" in brief
    assert str(context.resolve()) in brief


def test_a_local_only_case_stays_local_in_the_decision_command(repo_root: Path, capsys) -> None:
    case = _init(repo_root, "local")
    report = case / "report.md"
    report.write_text(
        report.read_text(encoding="utf-8").replace(
            "<!-- research:placeholder -->",
            "Churn rose from 2 to 3 percent in June, and pricing explains most of it.",
            1,
        ),
        encoding="utf-8",
    )

    assert "--local-only" in _next(capsys, case.name)
