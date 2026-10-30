"""One table generates each client's edit hook, and the hook reports without blocking."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from support.cases import fill_case

from agentic_research_loop.agent_hooks import (
    CLIENT_HOOKS,
    HOOK_SCRIPT,
    edited_files,
    hook_report,
    install_hooks,
)
from agentic_research_loop.cli import main
from agentic_research_loop.repo_setup import PACKAGE, setup_repo
from agentic_research_loop.sources import SourceConfigError

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE / "hooks" / "report-edit.sh"


@pytest.fixture(autouse=True)
def _in_repo(repo_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(repo_root)


def test_setup_installs_each_client_hook_once(repo_root: Path) -> None:
    actions = setup_repo(repo_root)

    for hook in CLIENT_HOOKS.values():
        assert f"added the edit hook to {hook.file}" in actions
        assert (repo_root / hook.file).is_file()
    assert (repo_root / HOOK_SCRIPT).resolve() == SCRIPT.resolve()
    assert setup_repo(repo_root) == []


def test_setup_keeps_a_users_own_hook(repo_root: Path) -> None:
    settings = repo_root / ".claude" / "settings.json"
    settings.parent.mkdir()
    mine = {"matcher": "Bash", "hooks": [{"type": "command", "command": "mine"}]}
    settings.write_text(
        json.dumps({"hooks": {"PostToolUse": [mine]}}), encoding="utf-8"
    )

    install_hooks(repo_root)

    entries = json.loads(settings.read_text())["hooks"]["PostToolUse"]
    assert entries[0] == mine
    assert len(entries) == 2


def test_a_malformed_hook_file_changes_nothing(repo_root: Path) -> None:
    settings = repo_root / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"hooks": {"PostToolUse": "oops"}}', encoding="utf-8")

    with pytest.raises(SourceConfigError, match="Fix: make it a list"):
        install_hooks(repo_root)

    assert not (repo_root / ".codex" / "hooks.json").exists()


@pytest.mark.parametrize(
    ("hook_input", "expected"),
    [
        ('{"tool_input": {"file_path": "/r/a.py"}}', ["a.py"]),
        ('{"file_path": "/r/b.md", "edits": []}', ["b.md"]),
        (
            json.dumps(
                {
                    "cwd": "/r",
                    "tool_input": {
                        "command": "*** Begin Patch\n*** Update File: a.py\n"
                        "*** Add File: b/c.md\n*** Delete File: d.py\n*** End Patch"
                    },
                }
            ),
            ["a.py", "b/c.md"],
        ),
        ("not json", []),
    ],
)
def test_edited_files_reads_each_client(hook_input: str, expected: list[str]) -> None:
    assert edited_files(hook_input, Path("/r")) == [
        str(Path("/r") / path) for path in expected
    ]


def test_hook_report_uses_each_clients_output_key() -> None:
    for client in ("claude", "codex"):
        output = json.loads(hook_report(client, "bad"))["hookSpecificOutput"]
        assert output == {"hookEventName": "PostToolUse", "additionalContext": "bad"}
    assert json.loads(hook_report("cursor", "bad")) == {"additional_context": "bad"}


def test_this_repo_commits_the_generated_hooks() -> None:
    """Agents working here get the hook with no setup, and it cannot drift."""
    assert install_hooks(ROOT) == []
    assert (ROOT / HOOK_SCRIPT).resolve() == SCRIPT.resolve()


def test_lint_reports_only_the_edited_file(repo_root: Path, capsys) -> None:
    case = repo_root / "research" / "2026-01-01-case"
    case.mkdir(parents=True)
    fill_case(case)
    (case / "source-objects.md").write_text("- no locator here\n", encoding="utf-8")
    report = case / "report.md"
    report.write_text(report.read_text() + "\nSee [C9].\n", encoding="utf-8")
    capsys.readouterr()

    assert main(["lint", str(report)]) == 1

    out = capsys.readouterr().out
    assert "report.md:" in out
    assert "[C9]" in out
    assert "no locator" not in out


def test_lint_always_reports_a_safety_finding(repo_root: Path, capsys) -> None:
    case = repo_root / "research" / "2026-01-01-case"
    case.mkdir(parents=True)
    fill_case(case)
    (case / "queries.sql").write_text("DROP TABLE t;\n", encoding="utf-8")

    assert main(["lint", str(case / "notes.md")]) == 1

    assert "not read-only" in capsys.readouterr().out


def test_lint_ignores_a_file_with_no_check(repo_root: Path, capsys) -> None:
    other = repo_root / "notes.txt"
    other.write_text("x", encoding="utf-8")

    assert main(["lint", str(other)]) == 0
    assert capsys.readouterr().out == ""


def test_lint_reports_a_scaffold_and_a_broken_bundle(repo_root: Path, capsys) -> None:
    assert main(["source", "new", "zendesk"]) == 0
    bundle = repo_root / "examples" / "sources" / "zendesk.toml"
    capsys.readouterr()

    assert main(["lint", str(bundle)]) == 1
    assert "still marked TODO" in capsys.readouterr().out

    bundle.write_text("not toml", encoding="utf-8")
    assert main(["lint", str(bundle)]) == 1
    assert "Fix: correct the syntax" in capsys.readouterr().out


def test_lint_reports_a_broken_sources_file(repo_root: Path, capsys) -> None:
    sources = repo_root / "config" / "sources.json"
    sources.parent.mkdir()
    sources.write_text("{bad", encoding="utf-8")

    assert main(["lint", str(sources)]) == 1
    assert "config/sources.json" in capsys.readouterr().out

    sources.write_text('{"sources": {}}', encoding="utf-8")
    assert main(["lint", str(sources)]) == 0


def test_lint_reports_a_missing_file(capsys) -> None:
    assert main(["lint", "gone.md"]) == 1
    assert "Fix: pass a file that exists" in capsys.readouterr().out


def _run_script(tmp_path: Path, *args: str, stdin: str = "") -> tuple[int, str, str]:
    """Run the script in `tmp_path/repo`, with a stub `uv` that logs each tool it runs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    stub = bin_dir / "uv"
    stub.write_text(
        f'#!/bin/sh\nshift 3\necho "$*" >> {log}\n'
        'case "$*" in\n'
        '  "research hook files") cat ;;\n'
        '  "research hook report"*) echo "{\\"wrapped\\": \\"$(cat)\\"}" ;;\n'
        '  "research lint --local-cases") ;;\n'
        '  "research lint"*) echo "report.md: bad. Fix: good." ;;\n'
        '  "ruff check"*) echo "a.py:1:1: F401" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    done = subprocess.run(
        ["sh", str(SCRIPT), *args],
        cwd=tmp_path / "repo",
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    return done.returncode, done.stdout, log.read_text() if log.exists() else ""


def _run_script_with_broken_env(
    tmp_path: Path, broken: str = "research", crashed: str = ""
) -> tuple[int, str, str]:
    """Run quick mode where `uv run <broken>` cannot start, or `<crashed>` dies silently."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "uv"
    stub.write_text(
        "#!/bin/sh\nshift 3\n"
        f'case "$1" in\n  "{broken}") [ -z "{crashed}" ] && exit 2 ;;\n'
        f'  "{crashed}") [ "$2" = --version ] || {{ echo crashed; exit 1; }} ;;\n'
        "esac\nexit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    done = subprocess.run(
        ["sh", str(SCRIPT)],
        cwd=tmp_path / "repo",
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    return done.returncode, done.stdout, done.stderr


def test_the_hook_routes_a_python_edit_and_never_blocks(tmp_path: Path) -> None:
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "a.py").write_text("import os\n", encoding="utf-8")

    code, out, calls = _run_script(tmp_path, "claude", stdin="a.py\n")

    assert code == 0
    assert "F401" in out
    assert "wrapped" in out
    assert "ruff format --quiet a.py" in calls
    assert "ruff check --quiet --output-format=concise a.py" in calls
    assert "basedpyright a.py" in calls
    assert "research lint" not in calls


def test_the_hook_routes_a_case_edit_and_skips_a_deleted_file(tmp_path: Path) -> None:
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "report.md").write_text("x", encoding="utf-8")

    code, out, calls = _run_script(tmp_path, "cursor", stdin="report.md\ngone.py\n")

    assert code == 0
    assert "Fix: good" in out
    assert "research lint report.md" in calls
    assert "ruff" not in calls


def test_quick_fails_on_a_problem_and_passes_on_no_change(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    assert _run_script(tmp_path)[0] == 0

    (repo / "report.md").write_text("x", encoding="utf-8")
    code, out, _calls = _run_script(tmp_path)
    assert code == 1
    assert "Fix: good" in out


def test_quick_catches_a_write_in_an_ignored_local_case(
    repo_root: Path, capsys
) -> None:
    case = repo_root / "research" / "2026-01-01-case"
    case.mkdir(parents=True)
    fill_case(case)
    (case / "queries.sql").write_text("DROP TABLE t;\n", encoding="utf-8")
    capsys.readouterr()

    assert main(["lint", "--local-cases"]) == 1

    out = capsys.readouterr().out
    assert "research/2026-01-01-case/queries.sql:1: not read-only" in out


def test_local_cases_report_only_hard_findings(repo_root: Path, capsys) -> None:
    assert main(["init", "wip", "--local-only", "--question", "Why?"]) == 0
    capsys.readouterr()

    assert main(["lint", "--local-cases"]) == 0
    assert capsys.readouterr().out == ""


def test_quick_runs_the_local_case_check_with_no_changed_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    _code, _out, calls = _run_script(tmp_path)

    assert "research lint --local-cases" in calls


def test_quick_fails_and_names_setup_when_the_environment_is_missing(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")

    code, out, err = _run_script_with_broken_env(tmp_path)

    assert code != 0
    assert "uv sync --dev" in out + err


def test_quick_fails_when_a_python_tool_is_missing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")

    code, out, err = _run_script_with_broken_env(tmp_path, broken="ruff")

    assert code != 0
    assert "uv sync --dev" in out + err


def test_quick_handles_a_path_with_spaces(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "my notes.md").write_text("x", encoding="utf-8")
    (repo / "a b.py").write_text("x = 1\n", encoding="utf-8")

    _code, _out, calls = _run_script(tmp_path)

    assert "research lint my notes.md" in calls
    assert "ruff format --quiet a b.py" in calls


def test_a_crashed_type_checker_is_not_a_pass(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")

    code, out, _err = _run_script_with_broken_env(tmp_path, crashed="basedpyright")

    assert code == 1
    assert "crashed" in out


def test_the_hook_ignores_a_file_outside_the_repo(
    repo_root: Path, tmp_path: Path
) -> None:
    inside = repo_root / "a.py"
    outside = tmp_path / "elsewhere.py"

    found = edited_files(
        json.dumps({"tool_input": {"file_path": str(outside)}}), repo_root
    ) + edited_files(json.dumps({"file_path": str(inside)}), repo_root)

    assert found == [str(inside.resolve())]


def test_a_patch_path_is_read_against_the_hook_cwd(repo_root: Path) -> None:
    hook_input = json.dumps(
        {
            "cwd": str(repo_root),
            "tool_input": {
                "command": "*** Begin Patch\n*** Update File: a.py\n"
                "*** Update File: ../out.py\n*** End Patch"
            },
        }
    )

    assert edited_files(hook_input, repo_root) == [str((repo_root / "a.py").resolve())]


def test_hook_output_is_capped_with_a_command_for_the_rest() -> None:
    text = "\n".join(f"line {number}" for number in range(2000))

    context = json.loads(hook_report("claude", text))["hookSpecificOutput"][
        "additionalContext"
    ]

    assert len(context) < 2200
    last = context.splitlines()[-1]
    assert "more characters" in last
    assert "sh .agents/hooks/report-edit.sh" in last


def test_cursor_uses_the_event_whose_output_reaches_the_agent(repo_root: Path) -> None:
    install_hooks(repo_root)

    hooks = json.loads((repo_root / ".cursor" / "hooks.json").read_text())["hooks"]

    assert "afterFileEdit" not in hooks
    assert hooks["postToolUse"][0]["matcher"] == "Write"
    assert "report-edit.sh cursor" in hooks["postToolUse"][0]["command"]
