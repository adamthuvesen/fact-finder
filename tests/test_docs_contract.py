"""Keep the instruction surface small, and keep its links true."""

from __future__ import annotations

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
    text = (ROOT / ".agents" / "skills" / skill / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert limit in text


def test_no_tracked_file_names_the_private_company() -> None:
    """This repo is public, so a private name in any file is a leak."""
    name = "menti" + "meter"
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    leaks = [
        file
        for file in listed
        if (ROOT / file).is_file()
        and name in (ROOT / file).read_text("utf-8", errors="ignore").lower()
    ]

    assert leaks == []


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
