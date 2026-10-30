"""Every shipped bundle satisfies the read-only control it declares.

Each bundle names one control from a closed set. A config-checked control is tested
against the server definition's structure. A declared control lives outside any file
here, so its bundle's SETUP.md must name it. A test cannot prove the control is
correct upstream. That needs live verification.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentic_research_loop.doctor import allowlist_problem, control_problem
from agentic_research_loop.source_bundles import (
    PACKAGED_BUNDLES,
    Bundle,
    available_bundles,
    load_bundle,
)
from agentic_research_loop.sources import CONFIG_CHECKED

ROOT = Path(__file__).resolve().parents[1]


def _bundles() -> list[Bundle]:
    return [load_bundle(ROOT, name) for name in available_bundles(ROOT)]


def test_bundles_ship_inside_the_package_and_examples_points_at_them() -> None:
    assert (ROOT / "examples" / "sources").resolve() == PACKAGED_BUNDLES.resolve()
    assert len(_bundles()) >= 29


@pytest.mark.parametrize("bundle", _bundles(), ids=lambda b: b.name)
def test_bundle_satisfies_its_declared_control(bundle: Bundle, tmp_path: Path) -> None:
    control = bundle.spec.read_only_control
    setup = (bundle.path / "SETUP.md").read_text(encoding="utf-8")
    if control.mechanism in CONFIG_CHECKED:
        assert bundle.server is not None, "a config-checked control needs a server"
        if bundle.server.support_files:
            (tmp_path / "config").mkdir()
            for name in bundle.server.support_files:
                (tmp_path / "config" / name).write_bytes(
                    (bundle.path / name).read_bytes()
                )
        assert (
            control_problem(
                tmp_path, control, url=bundle.server.url or "", args=bundle.server.args
            )
            is None
        )
    else:
        assert control.detail.lower() in setup.lower()


def _server_bundles() -> list[Bundle]:
    return [bundle for bundle in _bundles() if bundle.server is not None]


@pytest.mark.parametrize("bundle", _server_bundles(), ids=lambda b: b.name)
def test_write_tools_are_named_in_setup(bundle: Bundle) -> None:
    """A deny entry must come from the bundle's documentation, never from a guess."""
    assert bundle.server is not None
    setup = (bundle.path / "SETUP.md").read_text(encoding="utf-8")
    for tool in bundle.server.write_tools:
        assert tool in setup, tool


@pytest.mark.parametrize("bundle", _server_bundles(), ids=lambda b: b.name)
def test_every_placeholder_in_a_definition_is_declared(bundle: Bundle) -> None:
    """Doctor can flag only declared placeholders, so an undeclared one goes unnoticed."""
    assert bundle.server is not None
    text = bundle.server.model_dump_json(exclude={"placeholders"})
    found = re.findall(r"YOUR[-_][A-Z_-]+|/absolute/path/\S+?\.\w+", text)
    assert set(found) == set(bundle.server.placeholders)


def test_shipped_snowflake_allowlist_is_read_only() -> None:
    text = (PACKAGED_BUNDLES / "snowflake" / "snowflake-mcp-tools.yaml").read_text(
        encoding="utf-8"
    )

    assert allowlist_problem(text) is None


_SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    "research",
}
# The decision record has to name the flags to explain why they are gone.
_BYPASS_FLAG_EXEMPT = {
    Path("tests/test_readonly_contract.py"),
    Path(".agents/docs/decisions/native-goals.md"),
}


def test_no_permission_bypass_flag_ships_anywhere() -> None:
    """The bypass flags existed only because the loop was headless."""
    banned = ("dangerously-skip-permissions", "dangerously-bypass-approvals")
    offenders = [
        relative
        for path in ROOT.rglob("*")
        if path.is_file()
        and not _SKIP_DIRS & set(path.parts)
        and (relative := path.relative_to(ROOT)) not in _BYPASS_FLAG_EXEMPT
        and any(
            flag in path.read_text(encoding="utf-8", errors="ignore") for flag in banned
        )
    ]

    assert offenders == []
