"""Tests for `research source enable/disable/list` and the generated client configs."""

from __future__ import annotations

import json
import tomllib
from unittest.mock import patch

import pytest

from agentic_research_loop import client_configs as cc
from agentic_research_loop import io as io_module
from agentic_research_loop import source_bundles as sb
from agentic_research_loop.sources import (
    OAuthClient,
    ServerDefinition,
    SourceConfigError,
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


def write_bundle(repo, name, spec, server=None):
    bundle = repo / "examples" / "sources" / name
    bundle.mkdir(parents=True)
    (bundle / "source.json").write_text(json.dumps({"sources": {name: spec}}))
    (bundle / "SETUP.md").write_text(
        f"# {name} (read-only)\n{spec['read_only_control']['detail']}\n"
    )
    if server is not None:
        (bundle / "mcp.snippet.json").write_text(json.dumps(server))


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
    return json.loads((repo / path).read_text())["permissions"]["deny"]


def test_enable_generates_every_client_shape_from_one_definition(repo):
    sb.enable_bundle(repo, "foo")

    assert _sources(repo)["foo"]["plan_line"] == "Foo for things."
    assert _claude(repo)["foo"] == {"type": "http", "url": "https://foo.example/mcp"}
    assert _cursor(repo)["foo"] == {"url": "https://foo.example/mcp"}
    assert _codex(repo)["foo"]["url"] == "https://foo.example/mcp"
    assert _codex(repo)["foo"]["enabled"] is True
    assert (
        set(_claude(repo))
        == set(_cursor(repo))
        == set(_codex(repo))
        == {"existing", "foo"}
    )


def test_enable_writes_deny_lists_for_known_write_tools(repo):
    sb.enable_bundle(repo, "foo")

    assert _deny(repo, ".claude/settings.json") == ["mcp__foo__delete_thing"]
    assert _deny(repo, ".cursor/cli.json") == ["Mcp(foo:delete_thing)"]
    assert _codex(repo)["foo"]["disabled_tools"] == ["delete_thing"]


def test_deny_lists_keep_entries_this_tool_does_not_own(repo):
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text(
        json.dumps({"permissions": {"deny": ["Bash(rm:*)"]}, "model": "x"})
    )

    sb.enable_bundle(repo, "foo")
    sb.disable_bundle(repo, "foo")

    settings = json.loads((repo / ".claude" / "settings.json").read_text())
    assert settings == {"permissions": {"deny": ["Bash(rm:*)"]}, "model": "x"}


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
    assert _deny(repo, ".claude/settings.json") == ["mcp__foo__delete_thing"]


def test_disable_reverses_enable(repo):
    sb.enable_bundle(repo, "foo")
    sb.disable_bundle(repo, "foo")

    assert "foo" not in _sources(repo)
    assert set(_claude(repo)) == set(_cursor(repo)) == set(_codex(repo)) == {"existing"}
    assert _deny(repo, ".claude/settings.json") == []
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
def test_a_users_server_is_a_collision_that_changes_nothing(repo, path, content):
    (repo / path).write_text(json.dumps(content))
    before = _snapshot(repo)

    with pytest.raises(SourceConfigError, match="was not added by research"):
        sb.enable_bundle(repo, "foo")

    assert _snapshot(repo) == before


def test_a_users_codex_server_and_its_env_are_a_collision(repo):
    path = repo / ".codex" / "config.toml"
    path.write_text(
        '[mcp_servers."foo"]\nurl = "mine"\n\n[mcp_servers.foo.env]\nA = "1"\n'
    )
    before = _snapshot(repo)

    with pytest.raises(SourceConfigError, match="already exists"):
        sb.enable_bundle(repo, "foo")

    assert _snapshot(repo) == before


def test_rewiring_keeps_user_values_and_restores_only_what_is_missing(repo):
    sb.enable_bundle(repo, "foo")
    claude = json.loads((repo / ".mcp.json").read_text())
    claude["mcpServers"]["foo"]["headers"] = {"X": "mine"}
    (repo / ".mcp.json").write_text(json.dumps(claude))
    codex = repo / ".codex" / "config.toml"
    codex.write_text(codex.read_text() + '\n[mcp_servers.foo.env]\nA = "1"\n')
    cursor = json.loads((repo / ".cursor" / "mcp.json").read_text())
    del cursor["mcpServers"]["foo"]
    (repo / ".cursor" / "mcp.json").write_text(json.dumps(cursor))

    sb.enable_bundle(repo, "foo")

    assert _claude(repo)["foo"]["headers"] == {"X": "mine"}
    assert _codex(repo)["foo"]["env"] == {"A": "1"}
    assert _cursor(repo)["foo"] == {"url": "https://foo.example/mcp"}


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
    with pytest.raises(SourceConfigError, match="No bundle"):
        sb.enable_bundle(repo, "nope")


def test_rejects_path_traversal(repo):
    with pytest.raises(SourceConfigError, match="Invalid bundle name"):
        sb.enable_bundle(repo, "../../etc")


def test_repo_bundle_wins_over_a_packaged_one(repo):
    write_bundle(repo, "github", {**SPEC, "plan_line": "Local override."}, None)

    assert sb.load_bundle(repo, "github").spec.plan_line == "Local override."


def test_packaged_bundles_reach_a_repo_without_examples(tmp_path):
    assert "github" in sb.available_bundles(tmp_path)


def test_bundle_must_define_its_own_source(repo):
    write_bundle(repo, "bar", SPEC, None)
    (repo / "examples" / "sources" / "bar" / "source.json").write_text(
        json.dumps({"sources": {"baz": SPEC}})
    )

    with pytest.raises(SourceConfigError, match="exactly the source"):
        sb.load_bundle(repo, "bar")


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
