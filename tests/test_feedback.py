"""Every common mistake names its file, what is wrong, and the exact fix."""

from __future__ import annotations

import json
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
from support.cases import fill_case

from agentic_research_loop.cli import main

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _in_repo(repo_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(repo_root)


def _complete_case(repo_root: Path) -> Path:
    case = repo_root / "research" / "2026-01-01-case"
    case.mkdir(parents=True)
    fill_case(case)
    return case


def _edit_evidence(change: Callable[[dict], None]) -> Callable[[Path], None]:
    def apply(case: Path) -> None:
        path = case / "evidence.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        change(document)
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")

    return apply


def _write(name: str, text: str) -> Callable[[Path], object]:
    return lambda case: (case / name).write_text(text, encoding="utf-8")


def _unknown_source(document: dict) -> None:
    document["claims"][0]["source_ids"] = ["S99"]


def _unknown_field(document: dict) -> None:
    document["claims"][0]["invented"] = "x"


def _bad_status(document: dict) -> None:
    document["coverage"][0]["status"] = "maybe"


def _missing_field(document: dict) -> None:
    del document["sources"][0]["route"]


CASE_MISTAKES = [
    pytest.param(
        _edit_evidence(_unknown_source),
        "evidence.json:",
        "claim C1 cites S99, but only S1 is declared. Fix: use S1, or add S99 to sources.",
        id="unknown-source",
    ),
    pytest.param(
        _edit_evidence(_unknown_field),
        "evidence.json:",
        'is not a known field. Fix: remove "invented".',
        id="unknown-field",
    ),
    pytest.param(
        _edit_evidence(_bad_status),
        "evidence.json:",
        "Fix: use 'used', 'unavailable' or 'not-needed'.",
        id="bad-literal",
    ),
    pytest.param(
        _edit_evidence(_missing_field),
        "evidence.json:",
        'is missing. Fix: add "route".',
        id="missing-field",
    ),
    pytest.param(
        _write("evidence.json", "{ not json"),
        "evidence.json:1:",
        "Fix: correct the JSON syntax.",
        id="bad-json",
    ),
    pytest.param(
        _write("queries.sql", "SELECT 1;\n\n-- a note\nDELETE FROM t;\n"),
        "queries.sql:4:",
        "Fix: remove the statement.",
        id="write-sql",
    ),
    pytest.param(
        _write("report.md", "# Research Report\n\n## Executive Summary\n\nShort.\n"),
        "report.md:",
        "Fix: state the answer",
        id="thin-report",
    ),
    pytest.param(
        lambda case: (case / "review.json").unlink(),
        "review.json:",
        "Fix: ask a new independent reviewer",
        id="no-review",
    ),
]


@pytest.mark.parametrize(("mistake", "where", "expected"), CASE_MISTAKES)
def test_a_case_mistake_names_its_file_and_fix(
    repo_root: Path, capsys, mistake, where: str, expected: str
) -> None:
    case = _complete_case(repo_root)
    mistake(case)

    assert main(["validate", case.name, "--strict"]) == 1
    out = capsys.readouterr().out

    line = next(entry for entry in out.splitlines() if expected in entry)
    assert line.startswith(where)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (["next", "no-such-case"], "Fix: pass a case from `research list`."),
        (["goal", "no-such-case"], "Fix: pass a case from `research list`."),
        (["source", "enable", "nope"], "Fix: use one of"),
        (["source", "enable", "../x"], "Fix: use lowercase letters"),
        (["init", "x", "--sources", "nope"], "Fix: use one of web-search"),
    ],
)
def test_a_cli_mistake_names_its_fix(
    repo_root: Path, capsys, command: list[str], expected: str
) -> None:
    assert main(command) == 1
    captured = capsys.readouterr()

    assert expected in captured.err
    assert captured.out == ""
    assert "Traceback" not in captured.err


def test_doctor_names_the_fix_for_a_tampered_server(repo_root: Path, capsys) -> None:
    assert main(["source", "enable", "github"]) == 0
    path = repo_root / ".mcp.json"
    path.write_text(path.read_text().replace("/readonly", ""), encoding="utf-8")
    capsys.readouterr()

    assert main(["doctor"]) == 1

    out = capsys.readouterr().out
    assert ".mcp.json: github breaks its url_suffix control" in out
    assert "Fix: run `research setup`" in out


def test_a_bad_bundle_names_its_line_and_fix(repo_root: Path, capsys) -> None:
    bundles = repo_root / "examples" / "sources"
    bundles.mkdir(parents=True)
    (bundles / "bad.toml").write_text(
        'setup = "x"\n[source]\ndisplay_name = "Bad"\ncategory = "nope"\n',
        encoding="utf-8",
    )

    assert main(["source", "enable", "bad"]) == 1

    err = capsys.readouterr().err
    assert "bad.toml:" in err
    assert "source.category is" in err
    assert "Fix: use 'built-in'" in err


@pytest.mark.parametrize(
    ("source", "fix"),
    [
        ("import subprocess\n", "Fix: remove the call"),
        ("import openai\n", "Fix: remove the import"),
        ("from pydantic import BaseModel\n", "Fix: subclass strict_model.StrictModel"),
    ],
)
def test_ruff_bans_name_their_fix(source: str, fix: str) -> None:
    out = subprocess.run(
        [
            "uv",
            "run",
            "--quiet",
            "--no-sync",
            "ruff",
            "check",
            "--quiet",
            "--stdin-filename",
            "src/agentic_research_loop/new.py",
            "--select",
            "TID251",
            "-",
        ],
        cwd=ROOT,
        input=source,
        capture_output=True,
        text=True,
        check=False,
    ).stdout

    assert fix in out


def test_ast_grep_rules_and_the_layer_contract_name_their_fix() -> None:
    rules = sorted((ROOT / "rules").glob("*.yml"))
    assert rules
    for rule in rules:
        assert "Fix: " in rule.read_text(encoding="utf-8"), rule.name
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for contract in project["tool"]["importlinter"]["contracts"]:
        assert "Fix: " in contract["name"]


@pytest.mark.parametrize(
    "query",
    [
        "SELECT week, failures FROM exports FOR UPDATE;",
        "SELECT week FROM exports FOR SHARE;",
        "SELECT week FROM exports LOCK IN SHARE MODE;",
    ],
)
def test_a_locking_clause_keeps_the_query(repo_root: Path, capsys, query: str) -> None:
    case = _complete_case(repo_root)
    (case / "queries.sql").write_text(f"{query}\n", encoding="utf-8")

    assert main(["validate", case.name]) == 1

    out = capsys.readouterr().out
    assert "queries.sql:1: not read-only" in out
    assert "Fix: remove the locking clause and keep the query" in out
    assert "remove the statement" not in out


def test_a_write_beside_a_locking_clause_says_to_remove_the_statement(
    repo_root: Path, capsys
) -> None:
    case = _complete_case(repo_root)
    (case / "queries.sql").write_text(
        "SELECT a FROM t FOR UPDATE; DELETE FROM t;\n", encoding="utf-8"
    )

    assert main(["validate", case.name]) == 1

    assert "Fix: remove the statement" in capsys.readouterr().out
