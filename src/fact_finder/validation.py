"""Validate durable case artifacts without inspecting agent runtime state.

Safety and rigour are separate. Safety always blocks: `queries.sql` must be read-only, and
evidence must stay inside the case. Rigour is a default a person can override with a reason,
which is recorded and labelled. A rigour check blocks only when passing would otherwise
produce a silently misleading result. Everything else warns.

A case's rigour is `exploratory` or `decision`. An exploratory case is a labelled quick
answer that needs no evidence manifest or review. A decision case needs the full evidence
contract. A brief with no rigour line is a decision case, so older cases keep their contract.

A gate cannot prove semantic truth or reviewer independence. `GATE_LIMITS` says so in the
CLI output, and the evidence contract explains it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from .evidence import (
    ACCEPTED_GAPS_END,
    ACCEPTED_GAPS_START,
    STALE_REVIEW,
    Finding,
    evidence_findings,
    load_evidence,
    without_accepted_gaps,
)
from .feedback import line_of, problem, validation_problems
from .io import extract_section, read_text, write_documents
from .layout import (
    brief_path,
    evidence_path,
    local_today,
    notes_path,
    plan_path,
    queries_path,
    report_path,
    source_objects_path,
)
from .readonly_sql import (
    ReadOnlySql,
    UnsafeSqlError,
    first_unsafe_line,
    locking_clause_is_the_problem,
)
from .source_bundles import sql_backed_families
from .strict_model import StrictModel
from .templates import (
    EXPLORATORY_LABEL,
    NO_SOURCE_FAMILIES,
    PLACEHOLDER,
    RESEARCH_SHAPE,
    RIGOUR,
    required_brief_fields,
)

GATE_LIMITS = (
    "A gate checks integrity and arithmetic. Semantic truth and reviewer independence "
    "cannot be proved by a gate; they require independent judgment."
)
MIN_SUBSTANTIVE_CONTENT_LENGTH = 60
VALID_TEMPLATES = frozenset({"exploration", "root-cause", "comparison"})
Rigour = Literal["exploratory", "decision"]
NEVER_OVERRIDDEN = frozenset({"safety", "structure"})
BLOCKS_AT_COMPLETION: dict[Rigour, frozenset[str]] = {
    "exploratory": frozenset({"answer", "wrong"}),
    "decision": frozenset({"answer", "wrong", "contract"}),
}
OVERRIDES_FILE = "overrides.json"
SOURCE_OBJECTS = "source-objects.md"

REQUIRED_FILES = {"brief.md": brief_path, "report.md": report_path}
EXPECTED_FILES = {
    "notes.md": notes_path,
    "queries.sql": queries_path,
    "source-objects.md": source_objects_path,
}
REPORT_SECTIONS = ("Evidence", "Reconciliation", "Rejected Leads", "Risks And Caveats")

# Field names a high-priority root-cause thread should carry. The research-spec
# skill writes these exact strings.
ROOT_CAUSE_DESIGN_FIELDS = (
    "Discriminating Test",
    "Strongest Rival",
    "Completion Threshold",
    "Cross-Check",
)
_ROOT_CAUSE_BRIEF_SECTIONS = (
    "Hypotheses",
    "Known Confounders",
    "Required Cross-Checks",
)

THREAD_PATTERN = re.compile(
    r"^###\s+(T[^\n:]*:[^\n]*?)\n(?P<body>.*?)(?=^###\s+T|\Z)", re.MULTILINE | re.DOTALL
)
FIELD_PATTERN = re.compile(r"^\*\*(?P<name>[^*]+):\*\*\s*(?P<value>.+)$", re.MULTILINE)
SOURCE_OBJECT_BULLET = re.compile(r"(?m)^- +(.*(?:\n[ \t]+.*)*)")
ACCESS_DATE = re.compile(r"\baccessed\s+(\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)
BACKTICKED = re.compile(r"`([^`]+)`")
BARE_URL = re.compile(r"https?://\S+")


class Override(StrictModel):
    """A person's recorded decision to accept what a rigour check would block."""

    reason: str = Field(min_length=1)
    accepted_at: str
    accepted: list[str]


class OverridesFile(StrictModel):
    overrides: list[Override]


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


def _report_findings(text: str, rigour: Rigour) -> list[Finding]:
    report = without_accepted_gaps(text)
    findings: list[Finding] = []
    if not report_has_substance(report):
        findings.append(
            Finding(
                "answer",
                problem(
                    "the Executive Summary is empty or too short",
                    "state the answer in at least "
                    f"{MIN_SUBSTANTIVE_CONTENT_LENGTH} characters under "
                    "`## Executive Summary`",
                    file="report.md",
                ),
            )
        )
    if rigour == "exploratory" and EXPLORATORY_LABEL not in report:
        findings.append(
            Finding(
                "answer",
                problem(
                    "the exploratory label line is missing",
                    f"add the line `{EXPLORATORY_LABEL}`",
                    file="report.md",
                ),
            )
        )
    findings.extend(
        Finding(
            "contract",
            problem(
                f"section {heading} is missing or unfilled",
                f"write `## {heading}`, or state why it does not apply",
                file="report.md",
                line=line_of(report, f"## {heading}"),
            ),
        )
        for heading in REPORT_SECTIONS
        if rigour == "decision" and _section_is_placeholder(report, heading)
    )
    unfilled = [
        heading
        for heading in REPORT_SECTIONS
        if rigour == "exploratory" and PLACEHOLDER in (extract_section(report, heading) or "")
    ]
    if unfilled:
        findings.append(
            Finding(
                "format",
                problem(
                    f"unfilled sections: {', '.join(unfilled)}",
                    "fill them, or delete them from this quick answer",
                    file="report.md",
                ),
            )
        )
    return findings


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
                problem(
                    f"entry {entry[:80]!r} has no locator or access date",
                    "write it as - `name or URL` (accessed YYYY-MM-DD)",
                    file=SOURCE_OBJECTS,
                    line=line_of(text, entry[:40]),
                )
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
            errors.append(
                problem(
                    f"entry {entry[:80]!r} has an invalid access date",
                    "use a real date as YYYY-MM-DD",
                    file=SOURCE_OBJECTS,
                    line=line_of(text, entry[:40]),
                )
            )
    return objects, errors


def _source_object_findings(case_path: Path, text: str | None) -> list[Finding]:
    if text is None:
        return []
    if PLACEHOLDER in text:
        return [
            Finding(
                "format",
                problem(
                    "still has its placeholder",
                    "list each object you read as - `name or URL` (accessed YYYY-MM-DD)",
                    file=SOURCE_OBJECTS,
                ),
            )
        ]
    objects, errors = parse_source_objects(text)
    findings = [Finding("format", error) for error in errors]
    if not objects and not errors:
        findings.append(
            Finding(
                "format",
                problem(
                    "lists no source object",
                    "add each object you read as - `name or URL` (accessed YYYY-MM-DD)",
                    file=SOURCE_OBJECTS,
                ),
            )
        )
    if not evidence_path(case_path).exists():
        return findings
    try:
        evidence = load_evidence(case_path)
    except OSError, UnicodeError, ValueError, ValidationError:
        return findings
    findings.extend(
        Finding(
            "format",
            problem(
                f"source {source.id}: locator {source.locator} is not listed",
                f"add - `{source.locator}` (accessed YYYY-MM-DD)",
                file=SOURCE_OBJECTS,
            ),
        )
        for source in evidence.sources
        if source.locator not in text
    )
    return findings


def _coverage_findings(case_path: Path, brief: str) -> list[Finding]:
    section = extract_section(brief, "Allowed Source Families")
    if section is None or not evidence_path(case_path).exists():
        return []
    try:
        evidence = load_evidence(case_path)
    except OSError, UnicodeError, ValueError, ValidationError:
        return []
    allowed = {name.strip() for name in section.split(",") if name.strip()}
    allowed.discard(NO_SOURCE_FAMILIES)
    covered = {item.family for item in evidence.coverage}
    return [
        Finding(
            "format",
            problem(
                f"coverage {mismatch} {family}, but Allowed Source Families in brief.md "
                f"{'does not' if family in covered else 'does'}",
                f"make the coverage entry for {family} and the brief agree",
                file="evidence.json",
            ),
        )
        for family, mismatch in (
            *((family, "lists") for family in sorted(covered - allowed)),
            *((family, "omits") for family in sorted(allowed - covered)),
        )
    ]


def _used_sql_families(case_path: Path) -> list[str]:
    """Return SQL-backed families this case marks as used in its coverage."""
    if not evidence_path(case_path).exists():
        return []
    try:
        evidence = load_evidence(case_path)
    except OSError, UnicodeError, ValueError, ValidationError:
        return []
    sql_backed = sql_backed_families(case_path.parent.parent)
    return sorted(
        item.family
        for item in evidence.coverage
        if item.status == "used" and item.family in sql_backed
    )


def _sql_provenance_findings(case_path: Path, queries: ReadOnlySql | None) -> list[Finding]:
    if queries is None or queries.statement_count:
        return []
    used = _used_sql_families(case_path)
    if used:
        return [
            Finding(
                "contract",
                problem(
                    f"no preserved query, but the case used {', '.join(used)}",
                    "preserve the read-only query you ran, or change the coverage status",
                    file="queries.sql",
                ),
            )
        ]
    if queries.no_sql_reason:
        return []
    return [
        Finding(
            "format",
            problem(
                "has no query and no reason for that",
                "preserve the query, or add `-- No SQL used: <reason>`",
                file="queries.sql",
            ),
        )
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


def _root_cause_findings(case_path: Path, brief_text: str) -> list[Finding]:
    """Check the design sections that make a root-cause case falsifiable."""
    findings = [
        Finding(
            "format",
            problem(
                f"this root-cause brief has no `## {heading}` section",
                f"add `## {heading}`",
                file="brief.md",
            ),
        )
        for heading in _ROOT_CAUSE_BRIEF_SECTIONS
        if f"## {heading}" not in brief_text
    ]
    plan_file = plan_path(case_path)
    if not plan_file.exists():
        return findings
    try:
        plan_text = read_text(plan_file)
    except (OSError, UnicodeError) as exc:
        return [
            *findings,
            Finding(
                "format",
                problem(f"could not read: {exc}", "save it as UTF-8", file="plan.md"),
            ),
        ]
    if "No plan yet" in plan_text:
        return findings
    threads = parse_plan_threads(plan_text)
    if not threads:
        return [
            *findings,
            Finding(
                "format",
                problem(
                    "has content but no numbered research threads",
                    "add headings such as `### T1: <thread>`",
                    file="plan.md",
                ),
            ),
        ]
    findings.extend(
        Finding(
            "format",
            problem(
                f"{heading} is high priority but has no {field_name}",
                f"add `**{field_name}:** <value>` to the thread",
                file="plan.md",
                line=line_of(plan_text, heading),
            ),
        )
        for heading, fields in threads
        if fields.get("Priority", "").lower() == "high"
        for field_name in ROOT_CAUSE_DESIGN_FIELDS
        if field_name not in fields
    )
    return findings


def _shape_findings(case_path: Path, brief: str) -> list[Finding]:
    match = RESEARCH_SHAPE.search(brief)
    if match is None:
        return [
            Finding(
                "format",
                problem(
                    "`## Scope` has no research shape",
                    "add `- Research shape: exploration`, `root-cause`, or `comparison`",
                    file="brief.md",
                ),
            )
        ]
    shape = match.group(1).lower()
    if shape not in VALID_TEMPLATES:
        return [
            Finding(
                "format",
                problem(
                    f"unknown research shape {shape!r}",
                    f"use one of: {', '.join(sorted(VALID_TEMPLATES))}",
                    file="brief.md",
                    line=line_of(brief, shape),
                ),
            )
        ]
    return _root_cause_findings(case_path, brief) if shape == "root-cause" else []


def _brief_field_findings(case_path: Path, brief: str) -> list[Finding]:
    """Check each required brief section. A consumer adds to the list in its pyproject."""
    return [
        Finding(
            "answer",
            problem(
                f"required section ## {name} is missing or unfilled",
                f"write its content under `## {name}`",
                file="brief.md",
                line=line_of(brief, f"## {name}"),
            ),
        )
        for name in required_brief_fields(case_path.parent.parent)
        if _section_is_placeholder(brief, name)
    ]


def case_rigour(brief: str) -> Rigour:
    match = RIGOUR.search(brief)
    return "exploratory" if match and match.group(1).lower() == "exploratory" else "decision"


def _read_case_files(
    case_path: Path,
) -> tuple[dict[str, str], list[Finding]]:
    texts: dict[str, str] = {}
    findings: list[Finding] = []
    for name, path_for in {**REQUIRED_FILES, **EXPECTED_FILES}.items():
        required = name in REQUIRED_FILES
        path = path_for(case_path)
        if not path.exists():
            findings.append(
                Finding(
                    "structure" if required else "format",
                    problem(
                        "the file is missing",
                        f"restore it, or create the case with `research init` to get {name}",
                        file=name,
                    ),
                )
            )
            continue
        try:
            texts[name] = read_text(path)
        except (OSError, UnicodeError) as exc:
            kind = "format"
            if required:
                kind = "structure"
            elif name == "queries.sql":
                # SQL that cannot be read cannot be shown to be read-only.
                kind = "safety"
            findings.append(
                Finding(
                    kind,
                    problem(f"could not read: {exc}", "save it as UTF-8", file=name),
                )
            )
    return texts, findings


def _all_findings(case_path: Path, rigour: Rigour, texts: dict[str, str]) -> list[Finding]:
    brief = texts["brief.md"]
    try:
        queries = ReadOnlySql.parse(texts.get("queries.sql", ""))
        findings: list[Finding] = []
    except UnsafeSqlError as exc:
        queries = None
        findings = [
            Finding(
                "safety",
                problem(
                    f"not read-only: {exc}",
                    "remove the locking clause and keep the query"
                    if locking_clause_is_the_problem(texts.get("queries.sql", ""))
                    else "remove the statement. This file keeps read-only SQL only",
                    file="queries.sql",
                    line=first_unsafe_line(texts.get("queries.sql", "")),
                ),
            )
        ]
    findings.extend(_shape_findings(case_path, brief))
    findings.extend(evidence_findings(case_path, strict_completion=rigour == "decision"))
    question = extract_section(brief, "Question")
    if question is not None and question.lower().startswith("research:"):
        findings.append(
            Finding(
                "format",
                problem(
                    "the question is still the scaffold text",
                    "write the specific question under `## Question`",
                    file="brief.md",
                    line=line_of(brief, question),
                ),
            )
        )
    findings.extend(_brief_field_findings(case_path, brief))
    findings.extend(_coverage_findings(case_path, brief))
    findings.extend(_report_findings(texts["report.md"], rigour))
    findings.extend(_source_object_findings(case_path, texts.get("source-objects.md")))
    findings.extend(_sql_provenance_findings(case_path, queries))
    return findings


def _load_overrides(case_path: Path) -> list[Override]:
    path = case_path / OVERRIDES_FILE
    if not path.exists():
        return []
    try:
        return OverridesFile.model_validate_json(read_text(path)).overrides
    except ValidationError as exc:
        raise ValueError(
            "\n".join(validation_problems(exc, OVERRIDES_FILE, read_text(path)))
        ) from exc


@dataclass(frozen=True)
class Assessment:
    rigour: Rigour
    strict: bool
    errors: list[str]
    warnings: list[str]
    hard_errors: list[str] = dataclass_field(default_factory=list[str])
    accepted: dict[str, list[str]] = dataclass_field(default_factory=dict[str, list[str]])

    @property
    def review_is_stale(self) -> bool:
        return any(STALE_REVIEW in item for item in [*self.warnings, *self.accepted])

    @property
    def label(self) -> str:
        """Say what actually happened, including everything a person accepted."""
        if self.errors:
            return f"Not complete: {len(self.errors)} blocking findings."
        if not self.strict:
            return "Structure and read-only SQL checked. Completion not checked."
        if self.rigour == "exploratory":
            base = "Exploratory answer: no independent review."
        elif self.accepted:
            base = "Decision case with accepted gaps: not fully checked."
        elif self.review_is_stale:
            base = "Decision case: the review predates the latest edits."
        else:
            base = "Decision case: evidence checked and review fresh."
        gaps = [
            f'Accepted: "{_one_line(finding)}" because {"; ".join(reasons)}.'
            for finding, reasons in self.accepted.items()
        ]
        return " ".join([base, *gaps])


def _one_line(text: str, limit: int = 160) -> str:
    """Shorten a finding for a label: what was accepted, without how to fix it."""
    flat = " ".join(text.split(". Fix: ", maxsplit=1)[0].split())
    return flat if len(flat) <= limit else f"{flat[:limit]}..."


def assess_case(
    case_path: Path, *, strict_completion: bool = False, pinned: bool = False
) -> Assessment:
    """Classify every finding. `pinned` makes a stale review block."""
    texts, read_findings = _read_case_files(case_path)
    rigour = case_rigour(texts.get("brief.md", ""))
    if any(finding.kind == "structure" for finding in read_findings):
        findings = read_findings
    else:
        findings = [*read_findings, *_all_findings(case_path, rigour, texts)]
    blocking: frozenset[str] = frozenset()
    if strict_completion:
        blocking = BLOCKS_AT_COMPLETION[rigour]
        if pinned:
            blocking |= {"stale"}
    reasons: dict[str, list[str]] = {}
    for override in _load_overrides(case_path):
        for message in override.accepted:
            reasons.setdefault(message, []).append(override.reason)
    errors: list[str] = []
    warnings: list[str] = []
    hard_errors: list[str] = []
    accepted: dict[str, list[str]] = {}
    for finding in findings:
        if finding.kind in NEVER_OVERRIDDEN:
            errors.append(finding.message)
            hard_errors.append(finding.message)
        elif finding.kind not in blocking:
            warnings.append(finding.message)
        elif finding.message in reasons:
            accepted[finding.message] = reasons[finding.message]
        else:
            errors.append(finding.message)
    return Assessment(
        rigour=rigour,
        strict=strict_completion,
        errors=errors,
        warnings=warnings,
        hard_errors=hard_errors,
        accepted=accepted,
    )


def _render_accepted_gaps(overrides: list[Override]) -> str:
    lines = [
        f"- {_one_line(message)} Reason: {override.reason} ({override.accepted_at})"
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
        *_load_overrides(case_path),
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
