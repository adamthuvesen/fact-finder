from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_research_loop.cli import main
from agentic_research_loop.doctor import allowlist_problem, run_doctor
from agentic_research_loop.source_bundles import enable_bundle


def _statuses(repo: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for check in run_doctor(repo):
        result.setdefault(check.source, []).append(check.status)
    return result


def _edit_json(path: Path, edit) -> None:
    document = json.loads(path.read_text())
    edit(document)
    path.write_text(json.dumps(document))


@pytest.fixture()
def repo(repo_root, monkeypatch):
    monkeypatch.chdir(repo_root)
    return repo_root


def test_no_sources_is_clean_and_states_its_limit(repo, capsys) -> None:
    assert main(["doctor"]) == 0

    assert "does not contact or test the upstream server" in capsys.readouterr().out


def test_config_checked_control_passes_and_declared_control_is_only_declared(
    repo,
) -> None:
    enable_bundle(repo, "github")
    enable_bundle(repo, "linear")

    assert _statuses(repo) == {"github": ["pass"], "linear": ["declared"]}


def test_removed_readonly_suffix_fails(repo, capsys) -> None:
    enable_bundle(repo, "github")
    _edit_json(
        repo / ".mcp.json",
        lambda d: d["mcpServers"]["github"].update(
            url="https://api.githubcopilot.com/mcp"
        ),
    )

    assert main(["doctor"]) == 1

    assert ".mcp.json: url_suffix: url does not end with" in capsys.readouterr().out


def test_extra_flag_breaking_arg_absent_fails(repo) -> None:
    enable_bundle(repo, "duckdb")
    _edit_json(
        repo / ".cursor" / "mcp.json",
        lambda d: d["mcpServers"]["duckdb"]["args"].append("--read-write"),
    )

    assert "fail" in _statuses(repo)["duckdb"]


@pytest.mark.parametrize(
    ("bundle", "placeholder", "filled"),
    [
        ("slack", "YOUR_SLACK_CLIENT_ID", "123.456"),
        ("duckdb", "/absolute/path/to/your.duckdb", "/data/real.duckdb"),
        ("azure-devops", "YOUR_ADO_ORG", "contoso"),
        ("databricks", "YOUR-WORKSPACE", "acme"),
    ],
)
def test_placeholders_need_setup_until_filled(
    repo, capsys, bundle, placeholder, filled
) -> None:
    """Following SETUP.md must satisfy doctor, and `research setup` must keep the value."""
    enable_bundle(repo, bundle)

    assert "needs-setup" in _statuses(repo)[bundle]
    assert main(["doctor"]) == 1
    assert f"replace {placeholder}" in capsys.readouterr().out

    for path in (
        repo / ".mcp.json",
        repo / ".cursor/mcp.json",
        repo / ".codex/config.toml",
    ):
        path.write_text(path.read_text().replace(placeholder, filled))
    assert "needs-setup" not in _statuses(repo)[bundle]
    assert "fail" not in _statuses(repo)[bundle]

    assert main(["setup"]) == 0
    assert filled in (repo / ".mcp.json").read_text()
    assert placeholder not in (repo / ".codex/config.toml").read_text()
    assert "fail" not in _statuses(repo)[bundle]


@pytest.mark.parametrize(
    ("path", "edit"),
    [
        (".mcp.json", lambda d: d["mcpServers"].pop("github")),
        (".cursor/mcp.json", lambda d: d["mcpServers"].pop("github")),
    ],
)
def test_unwired_json_client_fails(repo, path, edit) -> None:
    enable_bundle(repo, "github")
    _edit_json(repo / path, edit)

    assert "fail" in _statuses(repo)["github"]


def test_unwired_codex_fails(repo) -> None:
    enable_bundle(repo, "github")
    (repo / ".codex" / "config.toml").write_text("[features]\ngoals = true\n")

    assert "fail" in _statuses(repo)["github"]


@pytest.mark.parametrize(
    ("path", "rule"),
    [
        (".claude/settings.json", "mcp__stripe__create_refund"),
        (".cursor/cli.json", "Mcp(stripe:create_refund)"),
    ],
)
def test_emptied_deny_list_fails(repo, capsys, path, rule) -> None:
    enable_bundle(repo, "stripe")
    assert main(["doctor"]) == 0
    capsys.readouterr()
    (repo / path).write_text(json.dumps({"permissions": {"deny": []}}))

    assert main(["doctor"]) == 1

    assert rule in capsys.readouterr().out


def test_codex_deny_list_removed_fails(repo, capsys) -> None:
    enable_bundle(repo, "stripe")
    path = repo / ".codex" / "config.toml"
    text = "\n".join(
        line for line in path.read_text().splitlines() if "disabled_tools" not in line
    )
    path.write_text(text + "\n")

    assert main(["doctor"]) == 1

    assert "does not deny create_refund" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("sql_statement_permissions: []\n", "allows no statement"),
        ("sql_statement_permissions:\n  - Select: false\n", "allows no statement"),
        ("sql_statement_permissions:\n  - Select: true\n  - Insert: 'true'\n", "Verb"),
        (
            "sql_statement_permissions:\n  - Select: true\n  - Drop : true\n",
            "allows Drop",
        ),
        ("other:\n  sql_statement_permissions:\n    - Select: true\n", "Verb"),
        ("{bad", "not valid YAML"),
        ("", "Verb"),
        (
            "sql_statement_permissions:\n  - Select: true\nother_services:\n"
            "  semantic_manager: true\n",
            "semantic_manager",
        ),
    ],
)
def test_allowlist_problems(text, problem) -> None:
    found = allowlist_problem(text)

    assert found is not None
    assert problem in found


def test_widened_snowflake_allowlist_fails(repo, capsys) -> None:
    enable_bundle(repo, "snowflake")
    path = repo / "config" / "snowflake-mcp-tools.yaml"
    path.write_text(path.read_text() + "  - Delete: true\n")

    assert main(["doctor"]) == 1

    assert "allows Delete" in capsys.readouterr().out


def test_missing_snowflake_allowlist_fails(repo) -> None:
    enable_bundle(repo, "snowflake")
    (repo / "config" / "snowflake-mcp-tools.yaml").unlink()

    assert "fail" in _statuses(repo)["snowflake"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[broken\n", "not valid TOML"),
        ("[features]\ngoals = false\n", "native goals are disabled"),
        ("[features]\nother = 1\n", "native goals are unset"),
    ],
)
def test_invalid_codex_file_or_disabled_goals_fails(
    repo, capsys, text, message
) -> None:
    (repo / ".codex").mkdir()
    (repo / ".codex" / "config.toml").write_text(text)

    assert main(["doctor"]) == 1

    assert message in capsys.readouterr().out
