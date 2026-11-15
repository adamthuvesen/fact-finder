"""Keep the instruction surface small, and keep its links true."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
from markdown_it import MarkdownIt

from fact_finder.source_bundles import available_bundles, load_bundle

ROOT = Path(__file__).resolve().parents[1]
# About 10% above the 994 lines counted on 2026-11-04. Lower it when text goes away.
INSTRUCTION_LIMIT = 1095
EXAMPLE_CASES = ("examples/",)


def _markdown_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return [ROOT / name for name in listed if (ROOT / name).is_file()]


def test_all_instruction_text_stays_under_the_limit() -> None:
    """Count every doc, skill, and reference. A bundle is read only for its own source."""
    counts = {
        str(path.relative_to(ROOT)): len(path.read_text(encoding="utf-8").splitlines())
        for path in _markdown_files()
        if not str(path.relative_to(ROOT)).startswith(EXAMPLE_CASES)
    }

    assert sum(counts.values()) < INSTRUCTION_LIMIT, counts


def _relative_links(text: str) -> list[str]:
    links = [
        str(child.attrGet("href"))
        for token in MarkdownIt().parse(text)
        for child in token.children or []
        if child.type == "link_open"
    ]
    return [
        link.split("#", 1)[0]
        for link in links
        if not re.match(r"[a-z]+:|#", link) and link.split("#", 1)[0]
    ]


def test_relative_doc_links_resolve() -> None:
    dead = [
        f"{path.relative_to(ROOT)}: {link}"
        for path in _markdown_files()
        for link in _relative_links(path.read_text(encoding="utf-8"))
        if not (path.parent / link).exists()
    ]

    assert dead == []


@pytest.mark.parametrize("skill", ["research-goal", "research-spec"])
@pytest.mark.parametrize("limit", ["Agent SDK", "nested slash command"])
def test_skills_keep_their_hard_limits(skill: str, limit: str) -> None:
    """Ruff bans the SDK in code. Only this text stops an agent running a skill."""
    text = (ROOT / ".agents" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")

    assert limit in text


PRIVATE_NAME = "menti" + "meter"
GIT_ENV = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}


def _files_naming(root: Path, name: str) -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        env=GIT_ENV,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return [
        file
        for file in listed
        if (root / file).is_file()
        and name in (root / file).read_text("utf-8", errors="ignore").lower()
    ]


def test_no_tracked_file_names_the_private_company() -> None:
    """This repo is public, so a private name in any file is a leak."""
    assert _files_naming(ROOT, PRIVATE_NAME) == []


def test_no_bundle_names_a_removed_file() -> None:
    for bundle in available_bundles(ROOT):
        text = load_bundle(ROOT, bundle).path.read_text(encoding="utf-8")
        for stale in (
            "SETUP.md",
            "source.json",
            "mcp.snippet.json",
            "](../",
            "the snippet",
        ):
            assert stale not in text, f"{bundle}: {stale}"


def test_mcp_json_is_not_tracked() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", ".mcp.json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert tracked == ""


def _missing_enforcer(cited: str) -> bool:
    if cited.startswith("make "):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        target = re.escape(cited.removeprefix("make "))
        return not re.search(rf"^{target}:", makefile, re.M)
    path, separator, name = cited.partition("::")
    if not separator or not (ROOT / path).is_file():
        return True
    definition = rf"^(def|class) {re.escape(name)}\b"
    return not re.search(definition, (ROOT / path).read_text(encoding="utf-8"), re.M)


def test_enforced_rules_cite_real_checks() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "\n## Enforced Rules\n" in text, (
        "AGENTS.md: no `## Enforced Rules` section. Fix: restore the heading and its table"
    )
    table = text.split("\n## Enforced Rules\n", 1)[1].split("\n## ", 1)[0]
    rows = [line.split("|") for line in table.splitlines() if line.startswith("| ")]
    cells = [row[2] for row in rows[2:]]
    uncited = [i for i, cell in enumerate(cells, 1) if not re.search(r"`[^`]+`", cell)]
    cited = [token for cell in cells for token in re.findall(r"`([^`]+)`", cell)]
    missing = [token for token in cited if _missing_enforcer(token)]

    assert cells, "AGENTS.md: Enforced Rules has no rows. Fix: restore the table"
    assert not uncited, f"AGENTS.md: Enforced Rules rows {uncited} cite nothing. Fix: cite a check"
    assert not missing, (
        f"AGENTS.md: Enforced Rules cites {missing}, which are not `path::name` defined "
        "in that file or a `make` target. Fix: cite the test function or make target"
    )


def test_the_doc_scans_find_known_cases(tmp_path: Path) -> None:
    """A scan that finds nothing passes. Prove each one still finds a known file, link, and name."""
    assert ROOT / "AGENTS.md" in _markdown_files()
    assert _relative_links("[a](docs/x.md#part) [b](https://e.com) [c](#top)") == ["docs/x.md"]
    assert not _missing_enforcer("make check")
    assert _missing_enforcer("make chec")
    assert not _missing_enforcer(
        "tests/test_docs_contract.py::test_enforced_rules_cite_real_checks"
    )
    assert _missing_enforcer("tests/test_docs_contract.py::test_enforced_rules")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, env=GIT_ENV, check=True)
    (tmp_path / "new.md").write_text(f"Built at {PRIVATE_NAME.title()}.", encoding="utf-8")
    assert _files_naming(tmp_path, PRIVATE_NAME) == ["new.md"]
