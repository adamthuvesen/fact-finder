"""Validate durable case artifacts without inspecting agent runtime state.

The native goal owns execution, so the only thing worth checking afterwards is the
record it left behind. `validate_case(..., strict_completion=True)` is the goal's
terminal condition. Every check here has to be something an agent can fix by doing
better research rather than by editing bookkeeping.

A gate cannot prove semantic truth or reviewer independence. `GATE_LIMITS` says so
in the CLI output, and docs/evidence-contract.md explains it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from .evidence import load_evidence, validate_evidence
from .io import extract_section, read_text
from .layout import (
    brief_path,
    evidence_path,
    notes_path,
    plan_path,
    queries_path,
    report_path,
    source_objects_path,
)
from .readonly_sql import ReadOnlySql, UnsafeSqlError
from .source_bundles import sql_backed_families
from .templates import NO_SOURCE_FAMILIES, PLACEHOLDER, RESEARCH_SHAPE

GATE_LIMITS = (
    "Checked evidence integrity, arithmetic, coverage, and review freshness. "
    "Semantic truth and reviewer independence cannot be proved by a gate; "
    "they require independent judgment."
)
MIN_SUBSTANTIVE_CONTENT_LENGTH = 60

VALID_TEMPLATES = frozenset({"exploration", "root-cause", "comparison"})

REQUIRED_FILES = {
    "brief.md": brief_path,
    "notes.md": notes_path,
    "report.md": report_path,
    "queries.sql": queries_path,
    "source-objects.md": source_objects_path,
}
REPORT_SECTIONS = ("Evidence", "Reconciliation", "Rejected Leads", "Risks And Caveats")

# Field names a high-priority root-cause thread must carry. The research-spec
# skill writes these exact strings; changing one here breaks that contract.
ROOT_CAUSE_DESIGN_FIELDS = (
    "Discriminating Test",
    "Strongest Rival",
    "Completion Threshold",
    "Cross-Check",
)

_ROOT_CAUSE_BRIEF_SECTIONS = (
    ("## Hypotheses", "root-cause brief should include a `## Hypotheses` section"),
    ("## Known Confounders", "root-cause brief should capture `## Known Confounders`"),
    (
        "## Required Cross-Checks",
        "root-cause brief should capture `## Required Cross-Checks`",
    ),
)

THREAD_PATTERN = re.compile(
    r"^###\s+(T[^\n:]*:[^\n]*?)\n(?P<body>.*?)(?=^###\s+T|\Z)", re.MULTILINE | re.DOTALL
)
FIELD_PATTERN = re.compile(r"^\*\*(?P<name>[^*]+):\*\*\s*(?P<value>.+)$", re.MULTILINE)
SOURCE_OBJECT_BULLET = re.compile(r"(?m)^- +(.*(?:\n[ \t]+.*)*)")
ACCESS_DATE = re.compile(r"\baccessed\s+(\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)
BACKTICKED = re.compile(r"`([^`]+)`")
BARE_URL = re.compile(r"https?://\S+")


@dataclass(frozen=True)
class SourceObject:
    """One `- `locator` ... (accessed YYYY-MM-DD)` entry of source-objects.md."""

    locator: str
    accessed: date


def _section_is_placeholder(text: str, heading: str) -> bool:
    section = extract_section(text, heading)
    return section is None or PLACEHOLDER in section


def report_has_substance(report_text: str) -> bool:
    summary = extract_section(report_text, "Executive Summary")
    if summary is None or PLACEHOLDER in summary:
        return False
    return len(" ".join(summary.split())) >= MIN_SUBSTANTIVE_CONTENT_LENGTH


def _report_errors(report: str) -> list[str]:
    errors = [
        f"report.md needs a completed {heading} section"
        for heading in REPORT_SECTIONS
        if _section_is_placeholder(report, heading)
    ]
    if not report_has_substance(report):
        errors.insert(0, "report.md needs a meaningful Executive Summary")
    return errors


def parse_source_objects(text: str) -> tuple[list[SourceObject], list[str]]:
    """Parse source-objects.md bullets into objects, returning any malformed entry."""
    objects: list[SourceObject] = []
    errors: list[str] = []
    for match in SOURCE_OBJECT_BULLET.finditer(text):
        entry = " ".join(match.group(1).split())
        locator = BACKTICKED.search(entry) or BARE_URL.search(entry)
        accessed = ACCESS_DATE.search(entry)
        if locator is None or accessed is None:
            errors.append(
                f"source-objects.md entry needs a backticked name or URL and "
                f"`accessed YYYY-MM-DD`: {entry[:80]}"
            )
            continue
        try:
            objects.append(
                SourceObject(
                    locator=locator.group(1) if locator.groups() else locator.group(),
                    accessed=date.fromisoformat(accessed.group(1)),
                )
            )
        except ValueError:
            errors.append(f"source-objects.md has an invalid access date: {entry[:80]}")
    return objects, errors


def _source_object_errors(case_path: Path, text: str) -> list[str]:
    if PLACEHOLDER in text:
        return ["source-objects.md still has its placeholder"]
    objects, errors = parse_source_objects(text)
    if not objects:
        return [*errors, "source-objects.md needs at least one concrete source object"]
    if not evidence_path(case_path).exists():
        return errors
    try:
        evidence = load_evidence(case_path)
    except (OSError, UnicodeError, ValueError, ValidationError):
        return errors
    listed = {item.locator for item in objects}
    errors.extend(
        f"{source.id}: locator {source.locator} is not listed in source-objects.md"
        for source in evidence.sources
        if source.locator not in listed
    )
    return errors


def _coverage_errors(case_path: Path, brief: str) -> list[str]:
    section = extract_section(brief, "Allowed Source Families")
    if section is None:
        return ["brief.md needs an `## Allowed Source Families` section"]
    if not evidence_path(case_path).exists():
        return []
    try:
        evidence = load_evidence(case_path)
    except (OSError, UnicodeError, ValueError, ValidationError):
        return []
    allowed = {name.strip() for name in section.split(",") if name.strip()}
    allowed.discard(NO_SOURCE_FAMILIES)
    if allowed != {item.family for item in evidence.coverage}:
        return ["evidence.json coverage must match the brief's Allowed Source Families"]
    return []


def _sql_errors(sql: str) -> tuple[list[str], ReadOnlySql | None]:
    try:
        return [], ReadOnlySql.parse(sql)
    except UnsafeSqlError as exc:
        return [f"queries.sql is not read-only: {exc}"], None


def _used_sql_families(case_path: Path) -> list[str]:
    """Return SQL-backed families this case marks as used in its coverage."""
    if not evidence_path(case_path).exists():
        return []
    try:
        evidence = load_evidence(case_path)
    except (OSError, UnicodeError, ValueError, ValidationError):
        return []
    sql_backed = sql_backed_families(case_path.parent.parent)
    return sorted(
        item.family
        for item in evidence.coverage
        if item.status == "used" and item.family in sql_backed
    )


def _sql_provenance_errors(case_path: Path, queries: ReadOnlySql | None) -> list[str]:
    if queries is None or queries.statement_count:
        return []
    used = _used_sql_families(case_path)
    if used:
        return [
            f"queries.sql needs a preserved read-only query: this case used "
            f"{', '.join(used)}, so `-- No SQL used` does not apply"
        ]
    if queries.no_sql_reason:
        return []
    return [
        "queries.sql needs a read-only query or an explicit `-- No SQL used: <reason>`"
    ]


def parse_plan_threads(plan_text: str) -> list[tuple[str, dict[str, str]]]:
    return [
        (
            match.group(1).strip(),
            {
                field.group("name").strip(): field.group("value").strip()
                for field in FIELD_PATTERN.finditer(match.group("body"))
            },
        )
        for match in THREAD_PATTERN.finditer(plan_text)
    ]


def _case_template(brief_text: str) -> tuple[str | None, list[str]]:
    """Read the case's research shape from the brief.

    An unreadable shape is an error rather than a silent `None`: falling through
    would skip the whole root-cause design contract while validation still passed.
    """
    match = RESEARCH_SHAPE.search(brief_text)
    if match is None:
        return None, [
            "brief.md needs a `- Research shape: <template>` line in `## Scope`"
        ]
    template = match.group(1).lower()
    if template not in VALID_TEMPLATES:
        return None, [
            f"brief.md has an unknown research shape {template!r}. "
            f"Use one of: {', '.join(sorted(VALID_TEMPLATES))}"
        ]
    return template, []


def _root_cause_design_errors(case_path: Path, brief_text: str) -> list[str]:
    """Check the design contract that makes a root-cause case falsifiable."""
    errors = [
        message
        for heading, message in _ROOT_CAUSE_BRIEF_SECTIONS
        if heading not in brief_text
    ]
    plan_file = plan_path(case_path)
    if not plan_file.exists():
        return errors
    try:
        plan_text = read_text(plan_file)
    except (OSError, UnicodeError) as exc:
        return [*errors, f"Could not read plan.md: {exc}"]
    if "No plan yet" in plan_text:
        return errors
    threads = parse_plan_threads(plan_text)
    if not threads:
        return [*errors, "plan.md has content but no numbered research threads"]
    errors.extend(
        f"{heading} is high priority but missing `{field_name}`"
        for heading, fields in threads
        if fields.get("Priority", "").lower() == "high"
        for field_name in ROOT_CAUSE_DESIGN_FIELDS
        if field_name not in fields
    )
    return errors


def validate_case(case_path: Path, *, strict_completion: bool = False) -> list[str]:
    """Validate durable case artifacts.

    The default pass checks structure, read-only SQL, and evidence integrity, and is
    safe at scaffold time. `strict_completion` adds the end-of-case gate.
    """
    errors: list[str] = []
    texts: dict[str, str] = {}
    for name, path_for in REQUIRED_FILES.items():
        path = path_for(case_path)
        if not path.exists():
            errors.append(f"Missing required file: {name}")
            continue
        try:
            texts[name] = read_text(path)
        except (OSError, UnicodeError) as exc:
            errors.append(f"Could not read {name}: {exc}")

    sql_errors, queries = _sql_errors(texts.get("queries.sql", ""))
    errors.extend(sql_errors)
    if errors:
        return errors

    brief = texts["brief.md"]
    template, template_errors = _case_template(brief)
    errors.extend(template_errors)
    if template == "root-cause":
        errors.extend(_root_cause_design_errors(case_path, brief))
    errors.extend(validate_evidence(case_path, strict_completion=strict_completion))
    if not strict_completion:
        return errors

    question = extract_section(brief, "Question")
    if question is None or question.lower().startswith("research:"):
        errors.append("brief.md needs a specific research question")
    errors.extend(_coverage_errors(case_path, brief))
    errors.extend(_report_errors(texts["report.md"]))
    errors.extend(_source_object_errors(case_path, texts["source-objects.md"]))
    errors.extend(_sql_provenance_errors(case_path, queries))
    return errors
