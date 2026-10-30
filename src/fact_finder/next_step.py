"""`research next`: read a case's state and say the next useful step. It is advice only."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from .io import extract_section, read_text
from .layout import brief_path
from .research import case_paths
from .sources import LOCAL_FAMILY
from .templates import NO_SOURCE_FAMILIES
from .validation import Assessment, assess_case

READ_FAILURES = (OSError, UnicodeError, ValueError, RecursionError)
RUN = "uv run research"
NOT_STARTED = "Executive Summary"
DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}-")
LOCAL_CONTEXT = re.compile(r"(?m)^- Local context folder: (.+)$")


def case_status(case_path: Path) -> str:
    try:
        if assess_case(case_path).errors:
            return "invalid"
        result = assess_case(case_path, strict_completion=True)
    except READ_FAILURES:
        return "invalid"
    if result.errors:
        return "in-progress"
    if result.accepted:
        return f"{result.rigour}-accepted"
    if result.review_is_stale:
        return f"{result.rigour}-stale-review"
    return f"{result.rigour}-complete"


def _decision_command(case: Path) -> str:
    """Rebuild the init command from the brief, so it can be pasted exactly as printed."""
    brief = read_text(brief_path(case))
    families = [
        family.strip()
        for family in (extract_section(brief, "Allowed Source Families") or "").split(",")
        if family.strip() not in {"", NO_SOURCE_FAMILIES, LOCAL_FAMILY}
    ]
    context_paths = LOCAL_CONTEXT.findall(extract_section(brief, "Source Constraints") or "")
    return shlex.join(
        [
            *RUN.split(),
            "init",
            f"{DATE_PREFIX.sub('', case.name)}-decision",
            "--rigour",
            "decision",
            "--question",
            extract_section(brief, "Question") or case.name,
            *(["--sources", ",".join(families)] if families else ["--local-only"]),
            *(flag for path in context_paths for flag in ("--context-path", path)),
        ]
    )


def _finished(case: Path, result: Assessment) -> list[str]:
    if result.review_is_stale:
        return [
            "Next: the review predates later edits. Ask a new independent reviewer for a "
            "new review if the edits are material.",
            f'Run: {RUN} review-snapshot "{case}"',
        ]
    lines = ["Nothing blocks completion."]
    lines.extend(f"Consider: {warning}" for warning in result.warnings)
    if result.rigour == "exploratory":
        lines.append(
            f"If this answer drives a decision that matters, run: {_decision_command(case)}"
        )
    return lines


def next_for_case(case: Path) -> list[str]:
    result = assess_case(case, strict_completion=True)
    head = f"Case: {case.name} ({result.rigour}, {case_status(case)})"
    validate = f'{RUN} validate "{case}" --strict'
    if result.hard_errors:
        return [head, f"Next: {result.hard_errors[0]}", f"Then run: {validate}"]
    if any(NOT_STARTED in error for error in result.errors):
        return [
            head,
            "Next: start the investigation inside a native goal.",
            f'Run: {RUN} goal "{case}"',
            "Then paste the printed /goal command into your agent client.",
        ]
    if result.errors:
        command = (
            f'{RUN} review-snapshot "{case}"'
            if len(result.errors) == 1 and "independent review is missing" in result.errors[0]
            else validate
        )
        return [
            head,
            f"Next: {result.errors[0]}",
            f"{len(result.errors)} blocking findings remain.",
            f"Run: {command}",
        ]
    return [head, *_finished(case, result)]


def next_for_repo(repo_root: Path) -> list[str]:
    cases = case_paths(repo_root)
    open_cases = sorted(
        (case for case in cases if case_status(case) in {"invalid", "in-progress"}),
        key=lambda case: case.stat().st_mtime,
        reverse=True,
    )
    if open_cases:
        lines = next_for_case(open_cases[0])
        others = ", ".join(case.name for case in open_cases[1:])
        return [*lines, f"Other open cases: {others}"] if others else lines
    return [
        "No open case.",
        f'Run: {RUN} init <slug> --question "<the question>"',
        f"See sources first: {RUN} source list",
    ]
