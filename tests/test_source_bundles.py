from __future__ import annotations

import json
import re
import tomllib
from unittest.mock import patch

import pytest
import tomlkit

from fact_finder import client_configs as cc
from fact_finder import io as io_module
from fact_finder import source_bundles as sb
from fact_finder.cli import main
from fact_finder.doctor import run_doctor
from fact_finder.repo_setup import setup_repo
from fact_finder.sources import (
    OAuthClient,
    ServerDefinition,
    SourceConfigError,
    Wiring,
)

SPEC = {
    "display_name": "Foo",
    "category": "work-context",
    "transport": "http-oauth",
    "read_only_control": {"mechanism": "credential", "detail": "view-only account"},
    "plan_line": "Foo for things.",
    "notes": "Search foo. Read-only.",
}
SERVER = {
    "server_name": "foo",
    "url": "https://foo.example/mcp",
    "write_tools": ["delete_thing"],
}


def write_bundle(repo, name, spec, server=None, connectors=None):
    bundles = repo / "examples" / "sources"
    bundles.mkdir(parents=True, exist_ok=True)
    document = {
        "setup": f"# {name} (read-only)\n{spec['read_only_control']['detail']}\n",
        "source": spec,
    }
    if server is not None:
        document["server"] = server
    if connectors is not None:
        document["connectors"] = connectors
    (bundles / f"{name}.toml").write_text(tomlkit.dumps(document))


@pytest.fixture()
def repo(tmp_path):
    """A fake repo with one `foo` bundle and an existing server in every client."""
    write_bundle(tmp_path, "foo", SPEC, SERVER)
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"existing": {"type": "http", "url": "x"}}})
    )
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"existing": {"url": "x"}}})
    )
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text(
        '# header\n\n[mcp_servers.existing]\nurl = "x"\nenabled = true\n'
    )
    return tmp_path


def _claude(repo):
    return json.loads((repo / ".mcp.json").read_text())["mcpServers"]


def _cursor(repo):
    return json.loads((repo / ".cursor" / "mcp.json").read_text())["mcpServers"]


def _codex(repo):
    return tomllib.loads((repo / ".codex" / "config.toml").read_text())["mcp_servers"]


def _sources(repo):
    return json.loads((repo / "config" / "sources.json").read_text())["sources"]


def _deny(repo, path):
    document = json.loads((repo / path).read_text())
    return document.get("permissions", {}).get("deny", [])


def test_enable_generates_every_client_shape_from_one_definition(repo):
    sb.enable_bundle(repo, "foo")

    assert _sources(repo)["foo"]["plan_line"] == "Foo for things."
    assert _claude(repo)["foo"] == {"type": "http", "url": "https://foo.example/mcp"}
    assert _cursor(repo)["foo"] == {"url": "https://foo.example/mcp"}
    assert _codex(repo)["foo"]["url"] == "https://foo.example/mcp"
    assert _codex(repo)["foo"]["enabled"] is True
    assert set(_claude(repo)) == set(_cursor(repo)) == set(_codex(repo)) == {"existing", "foo"}


def test_enable_writes_deny_lists_for_known_write_tools(repo):
    sb.enable_bundle(repo, "foo")

    assert _deny(repo, ".claude/settings.local.json") == ["mcp__foo__delete_thing"]
    assert _deny(repo, ".cursor/cli.json") == ["Mcp(foo:delete_thing)"]
    assert _codex(repo)["foo"]["disabled_tools"] == ["delete_thing"]


def test_deny_lists_keep_entries_this_tool_does_not_own(repo):
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.local.json").write_text(
        json.dumps({"permissions": {"deny": ["Bash(rm:*)"]}, "model": "x"})
    )

    sb.enable_bundle(repo, "foo")
    sb.disable_bundle(repo, "foo")

    settings = json.loads((repo / ".claude" / "settings.local.json").read_text())
    assert settings == {"permissions": {"deny": ["Bash(rm:*)"]}, "model": "x"}


def test_setup_denies_every_bundles_connector_writes_in_shared_settings(repo):
    write_bundle(repo, "foo", SPEC, SERVER, connectors=[{"name": "Foo"}])
    native = {**SPEC, "display_name": "Mail", "transport": "native"}
    write_bundle(repo, "mail", native, connectors=[{"name": "Mail", "write_tools": ["send"]}])
    shared = repo / ".claude" / "settings.json"
    shared.parent.mkdir()
    shared.write_text('{"model": "x", "permissions": {"deny": ["Read(./.env)"]}}')

    setup_repo(repo)
    setup_repo(repo)

    assert json.loads(shared.read_text())["model"] == "x"
    assert _deny(repo, ".claude/settings.json") == [
        "Read(./.env)",
        "mcp__claude_ai_Foo__delete_thing",
        "mcp__claude_ai_Mail__send",
    ]
    _edit_json_file(shared, lambda d: d["permissions"]["deny"].pop())
    assert [check.message for check in run_doctor(repo) if check.source == "mail"] == [
        ".claude/settings.json: does not deny mcp__claude_ai_Mail__send. "
        "Fix: run `research setup`, then commit the file."
    ]


def test_a_connector_needs_write_tools_to_deny(repo):
    write_bundle(repo, "mail", SPEC, connectors=[{"name": "Mail"}])

    with pytest.raises(SourceConfigError, match="connector Mail has no write tools"):
        sb.load_bundle(repo, "mail")


def _edit_json_file(path, edit):
    document = json.loads(path.read_text())
    edit(document)
    path.write_text(json.dumps(document))


def test_stdio_and_oauth_shapes():
    stdio = ServerDefinition(server_name="s", command="npx", args=["-y", "x"])
    oauth = ServerDefinition(
        server_name="o",
        url="https://o.test",
        oauth=OAuthClient(client_id="abc", callback_port=3118),
    )

    assert cc.claude_server(stdio) == {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "x"],
    }
    assert cc.cursor_server(stdio) == cc.claude_server(stdio)
    assert cc.codex_server(stdio)["args"] == ["-y", "x"]
    assert cc.claude_server(oauth)["oauth"] == {"clientId": "abc", "callbackPort": 3118}
    assert "oauth" not in cc.cursor_server(oauth)


def test_enable_is_idempotent(repo):
    sb.enable_bundle(repo, "foo")
    sb.enable_bundle(repo, "foo")

    text = (repo / ".codex" / "config.toml").read_text()
    assert text.count("[mcp_servers.foo]") == 1
    assert list(_sources(repo)) == ["foo"]
    assert _deny(repo, ".claude/settings.local.json") == ["mcp__foo__delete_thing"]


def test_disable_reverses_enable(repo):
    sb.enable_bundle(repo, "foo")
    sb.disable_bundle(repo, "foo")

    assert "foo" not in _sources(repo)
    assert set(_claude(repo)) == set(_cursor(repo)) == set(_codex(repo)) == {"existing"}
    assert _deny(repo, ".claude/settings.local.json") == []
    assert "# header" in (repo / ".codex" / "config.toml").read_text()


def test_disable_removes_a_servers_subtables(repo):
    sb.enable_bundle(repo, "foo")
    path = repo / ".codex" / "config.toml"
    path.write_text(path.read_text() + '\n[mcp_servers.foo.env]\nA = "1"\n')

    sb.disable_bundle(repo, "foo")

    assert set(tomllib.loads(path.read_text())["mcp_servers"]) == {"existing"}


def _snapshot(repo):
    return {str(path): path.read_bytes() for path in repo.rglob("*") if path.is_file()}


@pytest.mark.parametrize(
    ("path", "content"),
    [
        (".mcp.json", {"mcpServers": {"foo": {"type": "http", "url": "mine"}}}),
        (".cursor/mcp.json", {"mcpServers": {"foo": {"url": "mine"}}}),
    ],
)
def test_a_users_differing_server_stays_and_blocks_only_its_client(repo, path, content):
    (repo / path).write_text(json.dumps(content))

    actions = sb.enable_bundle(repo, "foo")

    assert any(path in line and "Fix:" in line for line in actions)
    assert json.loads((repo / path).read_text()) == content
    assert "foo" in _codex(repo)


def test_a_users_codex_server_and_its_env_stay_untouched(repo):
    path = repo / ".codex" / "config.toml"
    original = '[mcp_servers."foo"]\nurl = "mine"\n\n[mcp_servers.foo.env]\nA = "1"\n'
    path.write_text(original)

    actions = sb.enable_bundle(repo, "foo")

    assert any(".codex/config.toml" in line and "Fix:" in line for line in actions)
    assert _codex(repo)["foo"] == {"url": "mine", "env": {"A": "1"}}
    assert "foo" in _claude(repo)


def test_rewiring_keeps_user_values_and_restores_only_what_is_missing(repo):
    sb.enable_bundle(repo, "foo")
    claude = json.loads((repo / ".mcp.json").read_text())
    claude["mcpServers"]["foo"]["headers"] = {"X": "mine"}
    claude["mcpServers"]["foo"]["client_extension"] = {"args": 3}
    (repo / ".mcp.json").write_text(json.dumps(claude))
    codex = repo / ".codex" / "config.toml"
    codex.write_text(codex.read_text() + '\n[mcp_servers.foo.env]\nA = "1"\n')
    cursor = json.loads((repo / ".cursor" / "mcp.json").read_text())
    del cursor["mcpServers"]["foo"]
    (repo / ".cursor" / "mcp.json").write_text(json.dumps(cursor))

    sb.enable_bundle(repo, "foo")

    assert _claude(repo)["foo"]["headers"] == {"X": "mine"}
    assert _claude(repo)["foo"]["client_extension"] == {"args": 3}
    assert _codex(repo)["foo"]["env"] == {"A": "1"}
    assert _cursor(repo)["foo"] == {"url": "https://foo.example/mcp"}


@pytest.mark.parametrize(
    ("path", "field", "value", "location"),
    [
        (".mcp.json", "args", 3, "args"),
        (".mcp.json", "args", ["-y", 3], "args[1]"),
        (".cursor/mcp.json", "url", 3, "url"),
        (".codex/config.toml", "disabled_tools", 3, "disabled_tools"),
        (".codex/config.toml", "disabled_tools", [3], "disabled_tools[0]"),
    ],
)
def test_setup_rejects_malformed_server_fields_without_writes(repo, path, field, value, location):
    sb.enable_bundle(repo, "foo")
    config = repo / path
    if config.suffix == ".toml":
        document = tomlkit.parse(config.read_text())
        document["mcp_servers"]["foo"][field] = value
        config.write_text(tomlkit.dumps(document))
    else:
        document = json.loads(config.read_text())
        document["mcpServers"]["foo"][field] = value
        config.write_text(json.dumps(document))
    before = _snapshot(repo)

    with pytest.raises(SourceConfigError) as caught:
        setup_repo(repo)

    assert str(config) in str(caught.value)
    assert f"server 'foo' field {location} must be" in str(caught.value)
    assert "Fix:" in str(caught.value)
    assert _snapshot(repo) == before


def test_setup_adds_a_write_tool_a_wired_bundle_gained(repo):
    sb.enable_bundle(repo, "foo")
    codex = repo / ".codex" / "config.toml"
    codex.write_text(codex.read_text() + '\n[mcp_servers.foo.env]\nA = "1"\n')
    write_bundle(
        repo,
        "foo",
        SPEC,
        {**SERVER, "write_tools": ["delete_thing", "purge_thing"]},
    )
    (repo / "pyproject.toml").write_text("[tool.fact-finder]\n")

    actions = setup_repo(repo)

    entry = _codex(repo)["foo"]
    assert entry["disabled_tools"] == ["delete_thing", "purge_thing"]
    assert entry["env"] == {"A": "1"}
    assert "mcp__foo__purge_thing" in _deny(repo, ".claude/settings.local.json")
    assert "Mcp(foo:purge_thing)" in _deny(repo, ".cursor/cli.json")
    assert any("denied" in action for action in actions)
    assert not [check for check in run_doctor(repo) if check.status == "fail"]
    assert not any("denied" in action for action in setup_repo(repo))


def test_doctor_message_is_true_when_setup_restores_codex_tools(repo):
    sb.enable_bundle(repo, "foo")
    codex = repo / ".codex" / "config.toml"
    codex.write_text(codex.read_text().replace('disabled_tools = ["delete_thing"]\n', ""))
    assert any("run `research setup`" in c.message for c in run_doctor(repo))

    setup_repo(repo)

    assert not [check for check in run_doctor(repo) if check.status == "fail"]


def test_setup_leaves_a_users_server_restriction_alone(repo):
    codex = repo / ".codex" / "config.toml"
    codex.write_text('[mcp_servers.foo]\nurl = "mine"\n')

    actions = sb.enable_bundle(repo, "foo")

    assert any("research did not add it" in line for line in actions)
    assert _codex(repo)["foo"] == {"url": "mine"}


def test_disable_never_touches_a_server_it_did_not_add(repo):
    before = _snapshot(repo)

    assert sb.disable_bundle(repo, "foo") == []

    assert _snapshot(repo) == before


def test_a_deny_rule_the_user_already_had_survives_disable(repo):
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text(
        json.dumps({"permissions": {"deny": ["mcp__foo__delete_thing"]}})
    )

    sb.enable_bundle(repo, "foo")
    sb.disable_bundle(repo, "foo")

    assert _deny(repo, ".claude/settings.json") == ["mcp__foo__delete_thing"]


def test_a_failed_write_restores_every_file(repo):
    """Sources are written first. If a client write fails, nothing stays half-enabled."""
    before = _snapshot(repo)
    real = io_module.write_text

    def fail_on_cursor(path, content):
        if path.name == "cli.json":
            raise OSError("read-only")
        real(path, content)

    with (
        patch.object(io_module, "write_text", fail_on_cursor),
        pytest.raises(OSError, match="read-only"),
    ):
        sb.enable_bundle(repo, "foo")

    assert _snapshot(repo) == before


def test_read_only_config_dir_leaves_clients_untouched(repo):
    (repo / "config").mkdir()
    (repo / "config").chmod(0o500)
    before = _snapshot(repo)
    try:
        with pytest.raises(OSError, match="ermission"):
            sb.enable_bundle(repo, "foo")
        assert _snapshot(repo) == before
    finally:
        (repo / "config").chmod(0o700)


def test_a_symlinked_config_stays_a_symlink(repo, tmp_path_factory):
    real = tmp_path_factory.mktemp("shared") / "mcp.json"
    real.write_text(json.dumps({"mcpServers": {}}))
    (repo / ".mcp.json").unlink()
    (repo / ".mcp.json").symlink_to(real)

    sb.enable_bundle(repo, "foo")

    assert (repo / ".mcp.json").is_symlink()
    assert "foo" in json.loads(real.read_text())["mcpServers"]


@pytest.mark.parametrize(
    ("source", "goals"),
    [
        ("[features]\ngoals = false\n", False),
        ("[features] # keep this comment\nother = 1\n", True),
        ('[mcp_servers."github"]\nurl = "x"\n', True),
    ],
)
def test_codex_edits_always_leave_valid_toml(repo, source, goals):
    path = repo / ".codex" / "config.toml"
    path.write_text(source)

    sb.enable_bundle(repo, "foo")

    parsed = tomllib.loads(path.read_text())
    assert parsed["features"]["goals"] is goals
    assert "foo" in parsed["mcp_servers"]


def test_invalid_toml_is_a_clean_error(repo):
    (repo / ".codex" / "config.toml").write_text("[broken\n")

    with pytest.raises(SourceConfigError, match="not valid TOML"):
        sb.enable_bundle(repo, "foo")


def test_malformed_config_aborts_before_any_write(repo):
    (repo / ".cursor" / "mcp.json").write_text("{bad")

    with pytest.raises(SourceConfigError, match="not a JSON object"):
        sb.enable_bundle(repo, "foo")

    assert not (repo / "config" / "sources.json").exists()
    assert "foo" not in _claude(repo)


def test_list_marks_enabled_bundles(repo):
    assert "    foo" in sb.render_bundle_list(repo).replace("  * foo", "ENABLED")
    sb.enable_bundle(repo, "foo")
    assert "* foo" in sb.render_bundle_list(repo)


def test_unknown_bundle_raises(repo):
    with pytest.raises(SourceConfigError, match="no bundle"):
        sb.enable_bundle(repo, "nope")


def test_rejects_path_traversal(repo):
    with pytest.raises(SourceConfigError, match="invalid bundle name"):
        sb.enable_bundle(repo, "../../etc")


def test_repo_bundle_wins_over_a_packaged_one(repo):
    write_bundle(repo, "github", {**SPEC, "plan_line": "Local override."}, None)

    assert sb.load_bundle(repo, "github").spec.plan_line == "Local override."


def test_packaged_bundles_reach_a_repo_without_examples(tmp_path):
    assert "github" in sb.available_bundles(tmp_path)


def test_mcpless_bundle_enables_without_touching_servers(repo):
    write_bundle(
        repo,
        "bare",
        {
            **SPEC,
            "transport": "cli",
            "read_only_control": {
                "mechanism": "credential_scope",
                "detail": "x.readonly",
            },
        },
    )

    actions = sb.enable_bundle(repo, "bare")
    assert "bare" in _sources(repo)
    assert set(_claude(repo)) == {"existing"}
    assert not any("server" in action for action in actions)

    sb.disable_bundle(repo, "bare")
    assert "bare" not in _sources(repo)


def test_snowflake_allowlist_is_copied_and_kept(tmp_path):
    sb.enable_bundle(tmp_path, "snowflake")
    copy = tmp_path / "config" / "snowflake-mcp-tools.yaml"
    assert "sql_statement_permissions" in copy.read_text()

    copy.write_text("edited\n")
    sb.enable_bundle(tmp_path, "snowflake")
    assert copy.read_text() == "edited\n"


def test_goals_flag_keeps_root_keys_and_other_features(repo):
    path = repo / ".codex" / "config.toml"
    path.write_text('model = "m"\n\n[features]\nother = true\n')

    sb.enable_bundle(repo, "foo")

    parsed = tomllib.loads(path.read_text())
    assert parsed["model"] == "m"
    assert parsed["features"] == {"other": True, "goals": True}


def test_goals_flag_is_written_even_for_an_mcpless_bundle(tmp_path) -> None:
    """`research source enable gsc` wires no server; the user still needs /goal."""
    sb.enable_bundle(tmp_path, "gsc")

    config = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text())
    assert config["features"]["goals"] is True


def _consumer(tmp_path, settings=""):
    (tmp_path / "pyproject.toml").write_text(f"[tool.fact-finder]\n{settings}", encoding="utf-8")
    return tmp_path


def test_a_scaffold_loads_lists_and_marks_what_to_fill(tmp_path):
    repo = _consumer(tmp_path)

    actions = sb.scaffold_bundle(repo, "zendesk")

    path = repo / "examples" / "sources" / "zendesk.toml"
    assert str(path) in actions[0]
    assert "zendesk" in sb.available_bundles(repo)
    assert sb.load_bundle(repo, "zendesk").spec.display_name == "Zendesk"
    unfilled = sb.unfilled_fields(path)
    assert unfilled
    assert all("Fix:" in line for line in unfilled)


def test_a_scaffold_cannot_be_enabled_until_it_is_filled(tmp_path):
    repo = _consumer(tmp_path)
    sb.scaffold_bundle(repo, "zendesk")
    path = repo / "examples" / "sources" / "zendesk.toml"

    with pytest.raises(SourceConfigError, match=r"zendesk\.toml:\d+: still marked TODO"):
        sb.enable_bundle(repo, "zendesk")
    assert not (repo / "config" / "sources.json").exists()

    path.write_text(path.read_text().replace("TODO: ", ""), encoding="utf-8")
    sb.enable_bundle(repo, "zendesk")
    assert "zendesk" in _sources(repo)


def test_a_scaffold_refuses_to_overwrite_and_a_bad_name(tmp_path):
    repo = _consumer(tmp_path)
    sb.scaffold_bundle(repo, "zendesk")

    with pytest.raises(SourceConfigError, match="already exists"):
        sb.scaffold_bundle(repo, "zendesk")
    with pytest.raises(SourceConfigError, match="invalid bundle name"):
        sb.scaffold_bundle(repo, "../x")


def test_a_consumer_sets_its_own_sources_dir(tmp_path):
    repo = _consumer(tmp_path, 'sources_dir = "our-sources"\n')

    sb.scaffold_bundle(repo, "zendesk")

    assert (repo / "our-sources" / "zendesk.toml").is_file()
    assert "zendesk" in sb.available_bundles(repo)


def test_a_consumer_bundle_overrides_a_packaged_one(tmp_path):
    repo = _consumer(tmp_path, 'sources_dir = "our-sources"\n')
    write_bundle(repo, "github", {**SPEC, "plan_line": "Ours."})
    (repo / "our-sources").mkdir()
    (repo / "examples" / "sources" / "github.toml").rename(repo / "our-sources" / "github.toml")

    assert sb.load_bundle(repo, "github").spec.plan_line == "Ours."


def test_sources_dir_must_stay_inside_the_repo(tmp_path):
    repo = _consumer(tmp_path, 'sources_dir = "../elsewhere"\n')

    with pytest.raises(SourceConfigError, match="outside the repo"):
        sb.available_bundles(repo)


def test_show_prints_control_write_tools_and_setup(repo):
    text = sb.render_bundle(repo, "foo")

    assert "credential: view-only account" in text
    assert "delete_thing" in text
    assert "view-only account" in text


@pytest.mark.parametrize("key", ["../../x", "/tmp/x", "a/b.yaml", "..", "a\\b"])
def test_a_support_file_must_be_a_plain_file_name(repo, key):
    server = {**SERVER, "support_files": {key: "x"}}
    write_bundle(repo, "foo", SPEC, server)
    outside = repo.parent / "x"

    with pytest.raises(SourceConfigError, match=r"foo\.toml.*plain file name.*Fix:"):
        sb.enable_bundle(repo, "foo")

    assert not outside.exists()
    assert not (repo / "config" / "sources.json").exists()


def test_enable_leaves_shared_claude_settings_alone(repo):
    shared = repo / ".claude" / "settings.json"
    shared.parent.mkdir()
    shared.write_text('{"hooks": {}}\n')

    sb.enable_bundle(repo, "foo")

    assert shared.read_text() == '{"hooks": {}}\n'
    assert _deny(repo, ".claude/settings.local.json") == ["mcp__foo__delete_thing"]
    assert not [c for c in run_doctor(repo) if "does not deny" in c.message]


def test_disable_leaves_no_empty_permissions_block(repo):
    sb.enable_bundle(repo, "foo")

    sb.disable_bundle(repo, "foo")

    for name in (".claude/settings.local.json", ".cursor/cli.json"):
        assert "permissions" not in json.loads((repo / name).read_text())


def test_disable_keeps_a_users_other_local_settings(repo):
    local = repo / ".claude" / "settings.local.json"
    local.parent.mkdir()
    local.write_text('{"permissions": {"allow": ["Bash(ls)"], "deny": ["Mine"]}}')
    sb.enable_bundle(repo, "foo")

    sb.disable_bundle(repo, "foo")

    assert json.loads(local.read_text())["permissions"] == {
        "allow": ["Bash(ls)"],
        "deny": ["Mine"],
    }


def test_a_rule_already_in_shared_settings_is_not_added_or_removed(repo):
    shared = repo / ".claude" / "settings.json"
    shared.parent.mkdir()
    shared.write_text('{"permissions": {"deny": ["mcp__foo__delete_thing"]}}')

    sb.enable_bundle(repo, "foo")
    assert _deny(repo, ".claude/settings.json") == ["mcp__foo__delete_thing"]
    assert not [c for c in run_doctor(repo) if "does not deny" in c.message]

    sb.disable_bundle(repo, "foo")
    assert _deny(repo, ".claude/settings.json") == ["mcp__foo__delete_thing"]


def test_the_scaffold_comment_prints_a_lint_command_that_works(tmp_path, monkeypatch, capsys):
    repo = _consumer(tmp_path)
    monkeypatch.chdir(repo)
    sb.scaffold_bundle(repo, "zendesk")
    text = (repo / "examples" / "sources" / "zendesk.toml").read_text()
    match = re.search(r"`research (lint [^`]+)`", text)
    assert match is not None
    command = match.group(1)
    capsys.readouterr()

    assert main(command.split()) == 1
    assert "still marked TODO" in capsys.readouterr().out


def _pull_disable(repo, name):
    """Do what a pull does: the source is gone, and the local client files are not."""
    path = repo / "config" / "sources.json"
    document = json.loads(path.read_text())
    del document["sources"][name]
    path.write_text(json.dumps(document))


def test_enable_writes_no_local_ownership_to_the_shared_sources_file(repo):
    sb.enable_bundle(repo, "foo")

    assert "wiring" not in json.loads((repo / "config" / "sources.json").read_text())
    assert (repo / ".research" / ".gitignore").read_text() == "*\n"


def test_a_pulled_disable_reports_drift_then_setup_removes_only_what_research_added(
    repo,
):
    local = repo / ".claude" / "settings.local.json"
    local.parent.mkdir()
    local.write_text('{"permissions": {"deny": ["Mine"]}}')
    sb.enable_bundle(repo, "foo")
    _pull_disable(repo, "foo")

    drift = [c for c in run_doctor(repo) if c.status == "fail"]
    assert drift
    assert all("run `research setup`" in check.message for check in drift)
    assert "foo" in drift[0].message

    actions = setup_repo(repo)

    assert "removed server 'foo' from all client configs" in actions
    assert set(_claude(repo)) == {"existing"}
    assert set(_cursor(repo)) == {"existing"}
    assert set(_codex(repo)) == {"existing"}
    assert _deny(repo, ".claude/settings.local.json") == ["Mine"]
    assert _deny(repo, ".cursor/cli.json") == []
    assert not [c for c in run_doctor(repo) if c.status == "fail"]
    assert setup_repo(repo) == []
    sb.enable_bundle(repo, "foo")
    assert "foo" in _claude(repo)


def test_a_pulled_disable_is_also_applied_by_enabling_another_source(repo):
    write_bundle(repo, "bar", SPEC, {**SERVER, "server_name": "bar"})
    sb.enable_bundle(repo, "foo")
    _pull_disable(repo, "foo")

    sb.enable_bundle(repo, "bar")

    assert set(_claude(repo)) == {"existing", "bar"}


def test_setup_never_removes_a_server_a_person_added_by_hand(repo):
    sb.enable_bundle(repo, "foo")
    claude = json.loads((repo / ".mcp.json").read_text())
    claude["mcpServers"]["mine"] = {"type": "http", "url": "https://mine.example"}
    (repo / ".mcp.json").write_text(json.dumps(claude))
    _pull_disable(repo, "foo")

    assert not [c for c in run_doctor(repo) if "mine" in c.message]
    setup_repo(repo)

    assert _claude(repo)["mine"] == {"type": "http", "url": "https://mine.example"}
    assert _claude(repo)["existing"] == {"type": "http", "url": "x"}


def test_a_changed_bundle_url_reaches_every_client_and_keeps_user_values(repo):
    sb.enable_bundle(repo, "foo")
    claude = json.loads((repo / ".mcp.json").read_text())
    claude["mcpServers"]["foo"]["headers"] = {"X": "mine"}
    (repo / ".mcp.json").write_text(json.dumps(claude))
    moved = "https://new.example/mcp"
    write_bundle(repo, "foo", SPEC, {**SERVER, "url": moved})
    assert any(c.status == "fail" for c in run_doctor(repo))

    actions = sb.enable_bundle(repo, "foo")

    assert any("updated server 'foo'" in action for action in actions)
    assert _claude(repo)["foo"]["url"] == moved
    assert _claude(repo)["foo"]["headers"] == {"X": "mine"}
    assert _cursor(repo)["foo"]["url"] == moved
    assert _codex(repo)["foo"]["url"] == moved
    assert _deny(repo, ".claude/settings.local.json") == ["mcp__foo__delete_thing"]
    assert not [c for c in run_doctor(repo) if c.status == "fail"]


def test_setup_keeps_a_value_the_bundle_lets_a_person_fill(repo):
    write_bundle(
        repo,
        "foo",
        SPEC,
        {
            **SERVER,
            "url": "https://YOUR-ORG.example/mcp",
            "placeholders": ["YOUR-ORG"],
        },
    )
    sb.enable_bundle(repo, "foo")
    claude = json.loads((repo / ".mcp.json").read_text())
    claude["mcpServers"]["foo"]["url"] = "https://acme.example/mcp"
    (repo / ".mcp.json").write_text(json.dumps(claude))

    setup_repo(repo)

    assert _claude(repo)["foo"]["url"] == "https://acme.example/mcp"


def test_a_bundle_that_drops_its_server_is_unwired(repo):
    sb.enable_bundle(repo, "foo")
    write_bundle(repo, "foo", SPEC)

    setup_repo(repo)

    assert "foo" not in _claude(repo)
    assert _deny(repo, ".claude/settings.local.json") == []


def test_a_renamed_server_moves_with_its_deny_rules(repo):
    sb.enable_bundle(repo, "foo")
    write_bundle(repo, "foo", SPEC, {**SERVER, "server_name": "foo2"})

    setup_repo(repo)

    assert set(_claude(repo)) == {"existing", "foo2"}
    assert _deny(repo, ".claude/settings.local.json") == ["mcp__foo2__delete_thing"]


def test_a_deny_rule_stays_while_its_server_remains(repo):
    """Research owns the Cursor entry only, so the Claude entry and its rule are not its."""
    claude_rule = "mcp__foo__delete_thing"
    cursor_rule = "Mcp(foo:delete_thing)"
    (repo / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"foo": {"type": "http", "url": "mine"}}})
    )
    (repo / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"foo": {"url": "x"}}}))
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.local.json").write_text(
        json.dumps({"permissions": {"deny": [claude_rule]}})
    )
    (repo / ".cursor" / "cli.json").write_text(json.dumps({"permissions": {"deny": [cursor_rule]}}))
    configs = cc.ClientConfigs.read(repo)

    configs.unwire(
        Wiring(
            server_name="foo",
            clients=["cursor"],
            claude_deny=[claude_rule],
            cursor_deny=[cursor_rule],
        )
    )

    assert configs.server_entry("claude", "foo")
    assert cc.deny_rules(configs.claude_local_settings) == [claude_rule]
    assert not configs.server_entry("cursor", "foo")
    assert cc.deny_rules(configs.cursor_permissions) == []


def test_doctor_names_a_differing_entry_research_does_not_own(repo):
    sb.enable_bundle(repo, "foo")
    (repo / ".research" / "wiring.json").unlink()
    cursor = json.loads((repo / ".cursor" / "mcp.json").read_text())
    cursor["mcpServers"]["foo"]["url"] = "https://mine.example"
    (repo / ".cursor" / "mcp.json").write_text(json.dumps(cursor))

    drift = [c.message for c in run_doctor(repo) if c.status == "fail"]

    assert any(
        ".cursor/mcp.json" in message
        and "research did not add it" in message
        and "rename or remove" in message
        for message in drift
    )


def _fresh_clone(repo, codex_entry):
    """A committed Codex file and a shared sources file, and nothing local yet."""
    write_bundle(
        repo,
        "bar",
        SPEC,
        {**SERVER, "server_name": "bar", "url": "https://bar.example/mcp"},
    )
    (repo / "config").mkdir()
    (repo / "config" / "sources.json").write_text(
        json.dumps({"sources": {"foo": SPEC, "bar": SPEC}})
    )
    (repo / ".mcp.json").unlink()
    (repo / ".cursor" / "mcp.json").unlink()
    codex = repo / ".codex" / "config.toml"
    codex.write_text(f"[features]\ngoals = true\n\n[mcp_servers.foo]\n{codex_entry}\n")
    return codex


def test_a_committed_matching_entry_is_satisfied_on_a_fresh_clone(repo):
    codex = _fresh_clone(
        repo,
        'url = "https://foo.example/mcp"\nenabled = true\ndisabled_tools = ["delete_thing"]',
    )
    committed = codex.read_text()

    actions = setup_repo(repo)

    assert not [line for line in actions if "Fix:" in line]
    assert set(_claude(repo)) == {"foo", "bar"}
    assert set(_cursor(repo)) == {"foo", "bar"}
    assert _deny(repo, ".claude/settings.local.json") == [
        "mcp__bar__delete_thing",
        "mcp__foo__delete_thing",
    ]
    assert "foo" in _codex(repo)
    assert "mcp_servers.bar" in codex.read_text()
    assert codex.read_text().startswith(committed)
    assert not [c for c in run_doctor(repo) if c.status == "fail"]
    assert setup_repo(repo) == []


def test_a_matching_entry_research_did_not_add_survives_disable(repo):
    codex = _fresh_clone(
        repo,
        'url = "https://foo.example/mcp"\nenabled = true\ndisabled_tools = ["delete_thing"]',
    )
    setup_repo(repo)

    sb.disable_bundle(repo, "foo")

    assert "foo" in _codex(repo)
    assert 'url = "https://foo.example/mcp"' in codex.read_text()
    assert "foo" not in _claude(repo)
    assert "foo" not in _cursor(repo)
    assert "mcp__foo__delete_thing" not in _deny(repo, ".claude/settings.local.json")


@pytest.mark.parametrize(
    "entry",
    [
        'url = "https://mine.example/mcp"\ndisabled_tools = ["delete_thing"]',
        'url = "https://foo.example/mcp"',
    ],
    ids=["other-server", "write-tools-allowed"],
)
def test_a_differing_entry_stays_and_setup_finishes_the_rest(repo, entry):
    codex = _fresh_clone(repo, entry)
    committed = codex.read_text()

    actions = setup_repo(repo)

    problems = [line for line in actions if "Fix:" in line]
    assert len(problems) == 1
    assert ".codex/config.toml" in problems[0]
    assert codex.read_text().startswith(committed)
    assert "disabled_tools" not in _codex(repo)["foo"] or entry.startswith('url = "https://mine')
    assert set(_claude(repo)) == {"foo", "bar"}
    assert set(_cursor(repo)) == {"foo", "bar"}
    assert "bar" in _codex(repo)
    drift = [c.message for c in run_doctor(repo) if c.status == "fail"]
    assert len(drift) == 1
    assert ".codex/config.toml" in drift[0]
    assert "Fix:" in drift[0]


def test_setup_exits_non_zero_while_an_entry_needs_a_person(repo, monkeypatch, capsys):
    _fresh_clone(repo, 'url = "https://mine.example/mcp"')
    (repo / "pyproject.toml").write_text("[tool.fact-finder]\n")
    monkeypatch.chdir(repo)

    assert main(["setup"]) == 1

    assert "Fix:" in capsys.readouterr().out
    assert (repo / ".mcp.json").is_file()
