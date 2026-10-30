"""Every shipped bundle satisfies the read-only control it declares.

Each bundle names one control from a closed set. A config-checked control is tested
against the server definition's structure. A declared control lives outside any file
here, so its bundle's `setup` must name it. A test cannot prove the control is
correct upstream. That needs live verification.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fact_finder.doctor import allowlist_problem, control_problem
from fact_finder.source_bundles import (
    PACKAGED_BUNDLES,
    Bundle,
    available_bundles,
    load_bundle,
    repo_sources_dir,
)
from fact_finder.sources import CONFIG_CHECKED

ROOT = Path(__file__).resolve().parents[1]


def _bundles() -> list[Bundle]:
    return [load_bundle(ROOT, name) for name in available_bundles(ROOT)]


def test_bundles_ship_inside_the_package() -> None:
    assert repo_sources_dir(ROOT) == PACKAGED_BUNDLES.resolve()
    assert len(_bundles()) >= 29


@pytest.mark.parametrize("bundle", _bundles(), ids=lambda b: b.name)
def test_bundle_satisfies_its_declared_control(bundle: Bundle, tmp_path: Path) -> None:
    control = bundle.spec.read_only_control
    if control.mechanism in CONFIG_CHECKED:
        assert bundle.server is not None, "a config-checked control needs a server"
        if bundle.server.support_files:
            (tmp_path / "config").mkdir()
            for name, content in bundle.server.support_files.items():
                (tmp_path / "config" / name).write_text(content, encoding="utf-8")
        assert (
            control_problem(tmp_path, control, url=bundle.server.url or "", args=bundle.server.args)
            is None
        )
    else:
        assert control.detail.lower() in bundle.setup.lower()


def _server_bundles() -> list[Bundle]:
    return [bundle for bundle in _bundles() if bundle.server is not None]


@pytest.mark.parametrize("bundle", _server_bundles(), ids=lambda b: b.name)
def test_write_tools_are_named_in_setup(bundle: Bundle) -> None:
    """A deny entry must come from the bundle's documentation, never from a guess."""
    assert bundle.server is not None
    for tool in bundle.server.write_tools:
        assert tool in bundle.setup, tool


@pytest.mark.parametrize("bundle", _server_bundles(), ids=lambda b: b.name)
def test_every_placeholder_in_a_definition_is_declared(bundle: Bundle) -> None:
    """Doctor can flag only declared placeholders, so an undeclared one goes unnoticed."""
    assert bundle.server is not None
    text = bundle.server.model_dump_json(exclude={"placeholders", "support_files"})
    found = re.findall(r"YOUR[-_][A-Z_-]+|/absolute/path/\S+?\.\w+", text)
    assert set(found) == set(bundle.server.placeholders)


def test_shipped_snowflake_allowlist_is_read_only() -> None:
    server = load_bundle(ROOT, "snowflake").server
    assert server is not None
    assert allowlist_problem(server.support_files["snowflake-mcp-tools.yaml"]) is None


_SKIP_DIRS = {
    ".git",
    ".venv",
    ".verify",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    "research",
}
# These files name the flags to forbid them.
_BYPASS_FLAG_EXEMPT = {
    Path("tests/test_readonly_contract.py"),
    Path(".agents/docs/decisions/native-goals.md"),
    Path("AGENTS.md"),
}
_BYPASS_FLAG = re.compile(
    r"(?<![\w-])--(?:dangerously-skip-permissions|dangerously-bypass-approvals\S*"
    r"|yolo|full-auto|force)(?![\w-])"
)


def _bypass_flag_offenders(root: Path) -> list[Path]:
    return [
        relative
        for path in root.rglob("*")
        if path.is_file()
        and not _SKIP_DIRS & set(path.parts)
        and (relative := path.relative_to(root)) not in _BYPASS_FLAG_EXEMPT
        and _BYPASS_FLAG.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]


def test_no_permission_bypass_flag_ships_anywhere() -> None:
    """The bypass flags existed only because the loop was headless."""
    assert _bypass_flag_offenders(ROOT) == []


@pytest.mark.parametrize(
    "command",
    [
        "codex --yolo",
        "codex --full-auto",
        "claude --force",
        "claude --dangerously-skip-permissions",
        "codex --dangerously-bypass-approvals-and-sandbox",
    ],
)
def test_bypass_flag_scan_catches_each_flag(tmp_path: Path, command: str) -> None:
    (tmp_path / "run.sh").write_text(command, encoding="utf-8")

    assert _bypass_flag_offenders(tmp_path) == [Path("run.sh")]


def test_bypass_flag_scan_ignores_lookalike_flags(tmp_path: Path) -> None:
    (tmp_path / "run.sh").write_text("ruff --force-exclude", encoding="utf-8")

    assert _bypass_flag_offenders(tmp_path) == []
