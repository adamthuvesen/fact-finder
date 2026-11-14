from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import tomlkit

from fact_finder.cli import main
from fact_finder.doctor import allowlist_problem, run_doctor
from fact_finder.source_bundles import enable_bundle


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
        lambda d: d["mcpServers"]["github"].update(url="https://api.githubcopilot.com/mcp"),
    )

    assert main(["doctor"]) == 1

    assert "breaks its url_suffix control: url does not end with" in capsys.readouterr().out


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
        ("duckdb", "/absolute/path/to/your.duckdb", "md:"),
        ("duckdb", "/absolute/path/to/your.duckdb", "md:analytics"),
        ("azure-devops", "YOUR_ADO_ORG", "contoso"),
        ("databricks", "YOUR-WORKSPACE", "acme"),
    ],
)
def test_placeholders_need_setup_until_filled(repo, capsys, bundle, placeholder, filled) -> None:
    """Following SETUP.md must satisfy doctor, and `research setup` must keep the value."""
    enable_bundle(repo, bundle)

    assert "needs-setup" in _statuses(repo)[bundle]
    assert main(["doctor"]) == 1
    assert f"still has {placeholder}" in capsys.readouterr().out

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
        (".claude/settings.local.json", "mcp__stripe__create_refund"),
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
    text = "\n".join(line for line in path.read_text().splitlines() if "disabled_tools" not in line)
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
def test_invalid_codex_file_or_disabled_goals_fails(repo, capsys, text, message) -> None:
    (repo / ".codex").mkdir()
    (repo / ".codex" / "config.toml").write_text(text)

    assert main(["doctor"]) == 1

    assert message in capsys.readouterr().out


def _point_at(repo: Path, server: str, url: str) -> None:
    for path in (repo / ".mcp.json", repo / ".cursor" / "mcp.json"):
        _edit_json(path, lambda d: d["mcpServers"][server].update(url=url))


def test_a_declared_control_bundle_pointed_elsewhere_fails(repo, capsys) -> None:
    enable_bundle(repo, "linear")
    assert main(["doctor"]) == 0
    capsys.readouterr()

    _point_at(repo, "linear", "https://evil.example/mcp")

    assert main(["doctor"]) == 1
    output = capsys.readouterr().out
    assert "differs from its bundle: url" in output
    assert "differs from its bundle: url" in output


@pytest.mark.parametrize(
    ("bundle", "edit"),
    [
        ("stripe", lambda a: a.append("--api-key=x")),
        ("stripe", lambda a: a.__setitem__(1, "@evil/mcp")),
        ("azure", lambda a: a.remove("--read-only")),
        ("posthog", lambda a: a.__setitem__(2, "https://evil.example/mcp")),
    ],
)
def test_changed_or_added_args_fail(repo, bundle, edit) -> None:
    enable_bundle(repo, bundle)
    _edit_json(repo / ".mcp.json", lambda d: edit(d["mcpServers"][bundle]["args"]))

    assert "fail" in _statuses(repo)[bundle]


def test_a_placeholder_fill_cannot_change_the_host(repo) -> None:
    enable_bundle(repo, "databricks")
    _point_at(
        repo,
        "databricks",
        "https://evil.example/x.cloud.databricks.com/api/2.0/mcp/genie",
    )

    assert "fail" in _statuses(repo)["databricks"]


@pytest.mark.parametrize(
    ("bundle", "field", "value"),
    [
        ("amplitude", "url", "https://mcp.eu.amplitude.com/mcp"),
        ("mixpanel", "url", "https://mcp-in.mixpanel.com/mcp"),
        (
            "databricks",
            "url",
            "https://acme.cloud.databricks.com/api/2.0/mcp/genie/abc-1",
        ),
    ],
)
def test_setup_documented_urls_pass(repo, bundle, field, value) -> None:
    enable_bundle(repo, bundle)
    for path in (repo / ".mcp.json", repo / ".cursor" / "mcp.json"):
        _edit_json(path, lambda d: d["mcpServers"][bundle].update({field: value}))
    codex = repo / ".codex" / "config.toml"
    codex.write_text(re.sub(r'(?m)^url = ".*"$', f'url = "{value}"', codex.read_text()))

    assert "fail" not in _statuses(repo)[bundle]


@pytest.mark.parametrize(
    ("bundle", "edit"),
    [
        ("stripe", lambda a: a.__setitem__(2, "--tools=customers.read,invoices.read")),
        ("azure", lambda a: a.extend(["--namespace", "monitor"])),
        ("microsoft-365", lambda a: a.append("--allowed-scopes=Mail.Read")),
        ("redshift", lambda a: a.__setitem__(0, "awslabs.redshift-mcp-server@1.2.3")),
    ],
)
def test_setup_documented_args_pass(repo, bundle, edit) -> None:
    enable_bundle(repo, bundle)
    _edit_json(repo / ".mcp.json", lambda d: edit(d["mcpServers"][bundle]["args"]))

    assert "fail" not in _statuses(repo)[bundle]


def test_added_credentials_pass(repo) -> None:
    enable_bundle(repo, "datadog")
    _edit_json(
        repo / ".mcp.json",
        lambda d: d["mcpServers"]["datadog"].update(headers={"DD-API-KEY": "${KEY}"}),
    )

    assert "fail" not in _statuses(repo)["datadog"]


@pytest.mark.parametrize(
    ("path", "field", "value", "location"),
    [
        (".mcp.json", "args", 3, "args"),
        (".mcp.json", "args", "--read-only", "args"),
        (".mcp.json", "args", [3], "args[0]"),
        (".mcp.json", "url", 3, "url"),
        (".mcp.json", "command", ["npx"], "command"),
        (".cursor/mcp.json", "args", ["-y", None], "args[1]"),
        (".codex/config.toml", "args", 3, "args"),
        (".codex/config.toml", "disabled_tools", 3, "disabled_tools"),
        (".codex/config.toml", "disabled_tools", [{}], "disabled_tools[0]"),
    ],
)
def test_malformed_server_fields_fail_with_a_fix(
    repo, capsys, path, field, value, location
) -> None:
    enable_bundle(repo, "github")
    config = repo / path
    if config.suffix == ".toml":
        document = tomlkit.parse(config.read_text())
        document["mcp_servers"]["github"][field] = value
        config.write_text(tomlkit.dumps(document))
    else:
        _edit_json(config, lambda d: d["mcpServers"]["github"].update({field: value}))
    before = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}

    assert main(["doctor"]) == 1

    captured = capsys.readouterr()
    assert str(config) in captured.out
    assert f"server 'github' field {location} must be" in captured.out
    assert "Fix:" in captured.out
    assert "Traceback" not in captured.out + captured.err
    assert {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()} == before
