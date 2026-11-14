"""Tests for the source registry and the source lines a brief carries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import tomlkit
from pydantic import ValidationError

from fact_finder.cli import main
from fact_finder.source_bundles import load_registry
from fact_finder.sources import (
    BUILTIN_SOURCES,
    ServerDefinition,
    SourceConfigError,
    SourceSpec,
    source_constraints,
)

VALID_SPEC = {
    "display_name": "Zendesk",
    "category": "work-context",
    "transport": "stdio",
    "read_only_control": {"mechanism": "credential", "detail": "view-only agent"},
    "plan_line": "Zendesk for support tickets.",
    "notes": "Search support tickets. Read-only.",
}


def _enable(root: Path, specs: dict[str, Any]) -> None:
    """Write one bundle per spec and enable them all."""
    bundles = root / "examples" / "sources"
    bundles.mkdir(parents=True, exist_ok=True)
    for name, spec in specs.items():
        document = {"setup": "Read-only.", "source": spec}
        (bundles / f"{name}.toml").write_text(tomlkit.dumps(document), encoding="utf-8")
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "sources.json").write_text(
        json.dumps({"sources": list(specs)}), encoding="utf-8"
    )


def test_registry_is_builtins_plus_the_enabled_bundles(tmp_path) -> None:
    assert set(load_registry(tmp_path)) == set(BUILTIN_SOURCES)

    _enable(tmp_path, {"zendesk": VALID_SPEC})

    assert load_registry(tmp_path)["zendesk"].plan_line == VALID_SPEC["plan_line"]


@pytest.mark.parametrize(
    ("bad_spec", "match"),
    [
        ({**VALID_SPEC, "plan_line": ""}, "plan_line"),
        ({k: v for k, v in VALID_SPEC.items() if k != "plan_line"}, "plan_line"),
        ({**VALID_SPEC, "surprise": "x"}, "surprise"),
        ({**VALID_SPEC, "transport": "carrier-pigeon"}, "transport"),
        (
            {
                **VALID_SPEC,
                "read_only_control": {"mechanism": "trust-me", "detail": "x"},
            },
            "mechanism",
        ),
    ],
)
def test_registry_rejects_a_bad_spec(tmp_path, bad_spec, match) -> None:
    _enable(tmp_path, {"zendesk": bad_spec})

    with pytest.raises(SourceConfigError, match=match):
        load_registry(tmp_path)


def test_registry_rejects_an_enabled_source_with_no_bundle(tmp_path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "sources.json").write_text('{"sources": ["zendesk"]}')

    with pytest.raises(SourceConfigError, match="research source new zendesk"):
        load_registry(tmp_path)


def test_user_file_rejects_a_builtin_collision(tmp_path) -> None:
    _enable(tmp_path, {"web-search": VALID_SPEC})

    with pytest.raises(SourceConfigError, match="redefines the built-in"):
        load_registry(tmp_path)


def test_source_name_must_make_a_usable_identifier(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "sources.json").write_text('{"sources": ["Bad Name"]}')

    with pytest.raises(SourceConfigError, match="source name"):
        load_registry(tmp_path)


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"url": "https://x.test", "command": "npx"},
    ],
)
def test_server_defines_exactly_one_transport(fields) -> None:
    with pytest.raises(ValidationError, match="both or neither"):
        ServerDefinition(server_name="foo", **fields)


def test_constraints_list_plan_lines_hints_and_local_paths(tmp_path) -> None:
    registry = {"zendesk": SourceSpec.model_validate(VALID_SPEC)}

    lines = source_constraints(
        registry,
        ["zendesk"],
        hints={"zendesk": "billing tickets"},
        local_context_paths=[str(tmp_path)],
    )

    assert lines == [
        "Zendesk for support tickets.",
        "Zendesk focus: billing tickets",
        f"Local context folder: {tmp_path.resolve()}",
    ]


def test_sensitive_local_path_gets_a_note(tmp_path: Path) -> None:
    sensitive = tmp_path / ".ssh"
    sensitive.mkdir()

    lines = source_constraints({}, [], local_context_paths=[str(sensitive)])

    assert "Sensitive-looking path attached" in lines[1]


def test_local_only_leaves_no_external_source_in_the_brief(repo_root, monkeypatch) -> None:
    monkeypatch.chdir(repo_root)

    assert main(["init", "reg", "--template", "root-cause", "--local-only"]) == 0

    case = next((repo_root / "research").iterdir())
    brief = (case / "brief.md").read_text(encoding="utf-8")
    for spec in BUILTIN_SOURCES.values():
        assert spec.plan_line not in brief


@pytest.mark.parametrize(
    "command",
    [
        ["init", "x"],
        ["source", "disable", "github"],
        ["source", "enable", "github"],
        ["source", "list"],
        ["setup"],
        ["doctor"],
    ],
)
def test_bad_sources_json_is_a_clean_cli_error(repo_root, monkeypatch, capsys, command) -> None:
    """`{bad` used to raise a raw ValueError at import, on every command."""
    monkeypatch.chdir(repo_root)
    (repo_root / "config").mkdir()
    (repo_root / "config" / "sources.json").write_text("{bad", encoding="utf-8")

    assert main(command) == 1

    captured = capsys.readouterr()
    assert captured.err.startswith("config/sources.json")
    assert "Fix:" in captured.err
    assert captured.out == ""


def test_bad_sources_json_does_not_block_commands_that_never_read_it(
    repo_root, monkeypatch
) -> None:
    monkeypatch.chdir(repo_root)
    (repo_root / "config").mkdir()
    (repo_root / "config" / "sources.json").write_text("{bad", encoding="utf-8")

    assert main(["list"]) == 0
    assert main(["schema", "evidence"]) == 0
