"""`research lint`: report only what is wrong with the files just edited."""

from __future__ import annotations

from pathlib import Path

from .feedback import problem
from .research import case_paths
from .source_bundles import (
    PACKAGED_BUNDLES,
    load_bundle,
    repo_sources_dir,
    unfilled_fields,
)
from .sources import USER_SOURCES_FILE, SourceConfigError, load_sources_file
from .validation import assess_case

CASE_MARKER = "brief.md"


def _case_of(path: Path, repo_root: Path) -> Path | None:
    for parent in path.parents:
        if parent == repo_root:
            return None
        if (parent / CASE_MARKER).is_file():
            return parent
    return None


def _case_label(case: Path) -> str:
    return f"{case.parent.name}/{case.name}"


def local_case_problems(repo_root: Path) -> list[str]:
    """Report what `research validate` blocks on, in cases git cannot see."""
    problems: list[str] = []
    for case in case_paths(repo_root):
        try:
            errors = assess_case(case).errors
        except (OSError, UnicodeError, ValueError) as exc:
            errors = str(exc).split("\n")
        problems.extend(f"{_case_label(case)}/{error}" for error in errors)
    return problems


def _case_file_problems(path: Path, case: Path) -> list[str]:
    """Report what names this file, plus any hard failure, because safety is never scoped."""
    relative = path.relative_to(case).as_posix()
    try:
        result = assess_case(case, strict_completion=True)
    except (OSError, UnicodeError, ValueError) as exc:
        return str(exc).split("\n")
    found = [
        finding
        for finding in [*result.errors, *result.warnings]
        if relative in finding or finding in result.hard_errors
    ]
    return [f"{_case_label(case)}/{finding}" for finding in found]


def _bundle_problems(path: Path, repo_root: Path) -> list[str]:
    try:
        load_bundle(repo_root, path.stem)
    except SourceConfigError as exc:
        return str(exc).split("\n")
    return unfilled_fields(path)


def lint_file(raw_path: str, repo_root: Path) -> list[str]:
    """Check one file by what it is. A file with no check reports nothing."""
    path = Path(raw_path).resolve()
    if not path.is_file():
        return [problem(f"{raw_path} does not exist", "pass a file that exists", file=raw_path)]
    root = repo_root.resolve()
    if path == root / USER_SOURCES_FILE:
        try:
            load_sources_file(repo_root)
        except SourceConfigError as exc:
            return str(exc).split("\n")
        return []
    if path.suffix == ".toml" and path.parent in {
        repo_sources_dir(repo_root),
        PACKAGED_BUNDLES.resolve(),
    }:
        return _bundle_problems(path, repo_root)
    case = _case_of(path, root)
    return _case_file_problems(path, case) if case else []
