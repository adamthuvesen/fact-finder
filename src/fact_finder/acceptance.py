"""Record a person's acceptance of rigour blocks, in overrides.json and in the report."""

from __future__ import annotations

import json
from pathlib import Path

from .evidence_files import ACCEPTED_GAPS_END, ACCEPTED_GAPS_START, without_accepted_gaps
from .feedback import problem
from .io import read_text, write_documents
from .layout import local_today, report_path
from .overrides import OVERRIDES_FILE, Override, OverridesFile, load_overrides, one_line
from .research import resolve_case_path
from .validation import READ_FAILURES, Assessment, assess_case


def _render_accepted_gaps(overrides: list[Override]) -> str:
    lines = [
        f"- {one_line(message)} Reason: {override.reason} ({override.accepted_at})"
        for override in overrides
        for message in override.accepted
    ]
    return "\n".join(
        [
            ACCEPTED_GAPS_START,
            "## Accepted Gaps",
            "",
            "A person accepted these. Validation did not pass them.",
            "",
            *lines,
            ACCEPTED_GAPS_END,
            "",
        ]
    )


def accept_findings(case_path: Path, reason: str, *, pinned: bool = False) -> list[str]:
    """Record a person's override of the current rigour blocks, in the case and its report.

    Safety cannot be overridden. A repeat records the new reason for what it still covers.
    """
    text = reason.strip()
    if not text:
        raise ValueError(
            problem("--accept has no reason", 'use --accept "<why a person accepts this>"')
        )
    current = assess_case(case_path, strict_completion=True, pinned=pinned)
    accepted = [
        *(error for error in current.errors if error not in current.hard_errors),
        *current.accepted,
    ]
    if not accepted:
        return []
    overrides = [
        *load_overrides(case_path),
        Override(reason=text, accepted_at=local_today().isoformat(), accepted=accepted),
    ]
    report = report_path(case_path)
    body = without_accepted_gaps(read_text(report))
    write_documents(
        {
            case_path / OVERRIDES_FILE: json.dumps(
                OverridesFile(overrides=overrides).model_dump(), indent=2
            )
            + "\n",
            report: f"{body}\n{_render_accepted_gaps(overrides)}",
        }
    )
    return accepted


def assess_case_path(
    repo_root: Path, case: str, *, strict: bool, pinned: bool, accept: str | None
) -> tuple[str, Assessment]:
    """Resolve, accept if asked, and assess a case. A failure to read it becomes an error."""
    try:
        case_path = resolve_case_path(repo_root, case)
        if accept is not None:
            accept_findings(case_path, accept, pinned=pinned)
        return str(case_path), assess_case(case_path, strict_completion=strict, pinned=pinned)
    except READ_FAILURES as exc:
        return case, Assessment.unreadable(str(exc), strict=strict)
