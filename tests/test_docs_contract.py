"""Keep the instruction surface small, and keep AGENTS.md tied to real checks."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
INSTRUCTION_LIMIT = 500


def _instruction_files() -> list[Path]:
    return [
        ROOT / "AGENTS.md",
        ROOT / "program.md",
        ROOT / "README.md",
        ROOT / ".agents" / "docs" / "architecture.md",
        ROOT / ".agents" / "docs" / "setup.md",
        *sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md")),
    ]


def test_instruction_surface_stays_under_the_limit() -> None:
    counts = {
        str(path.relative_to(ROOT)): len(path.read_text(encoding="utf-8").splitlines())
        for path in _instruction_files()
    }

    assert sum(counts.values()) < INSTRUCTION_LIMIT, counts


def test_every_enforced_rule_names_a_check_that_exists() -> None:
    """A table row pointing at a deleted check would claim enforcement that is gone."""
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    section = agents.split("## Enforced rules", 1)[1].split("\n## ", 1)[0]
    rows = re.findall(r"^\| (?!Rule|---)(.+?) \| (.+?) \| (.+?) \|$", section, re.M)
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert len(rows) >= 8
    for rule, enforced_by, _added in rows:
        for reference in re.findall(r"`([^`]+)`", enforced_by):
            if reference.startswith("make "):
                assert f"\n{reference.removeprefix('make ')}:" in makefile, rule
            else:
                assert (ROOT / reference).exists(), f"{rule}: {reference}"


def _markdown_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return [ROOT / name for name in listed if (ROOT / name).is_file()]


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
    text = (ROOT / ".agents" / "skills" / skill / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert limit in text
