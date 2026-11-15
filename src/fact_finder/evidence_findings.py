"""Turn a case's evidence and review into findings that validation classifies."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import DecimalException, localcontext
from pathlib import Path
from typing import Literal, cast

from .evidence_files import (
    UnsafeArtifactPathError,
    case_file,
    case_file_digest,
    declared_query_ids,
    load_artifact,
    load_evidence,
    read_case_json,
    review_snapshot,
    without_accepted_gaps,
)
from .evidence_models import SCAFFOLD_COVERAGE_REASON, Calculation, Evidence, Review
from .feedback import line_of, problem
from .io import read_text
from .layout import as_table, evidence_path, report_path, review_path

STALE_REVIEW = "review.json is stale"
# How a validation finding behaves. `safety` and `structure` always block. `answer`, `wrong`,
# and `contract` block a completion check by policy. `stale` blocks only on request, and
# `format` never blocks. See `validation.assess_case`.
FindingKind = Literal["safety", "structure", "answer", "wrong", "contract", "stale", "format"]


@dataclass(frozen=True)
class Finding:
    kind: FindingKind
    message: str


def _calculation_error(calculation: Calculation) -> str | None:
    fix = "recompute result and record the correct value, or correct the inputs"
    values = [
        *(item.value for item in calculation.inputs),
        calculation.result,
        calculation.tolerance,
    ]
    exponents = [
        exponent for value in values if isinstance(exponent := value.as_tuple().exponent, int)
    ]
    try:
        with localcontext() as context:
            context.prec = max(
                28,
                max(value.adjusted() for value in values) - min(exponents) + len(values) + 2,
            )
            computed = calculation.computed_result()
            if not computed.is_finite():
                return problem(
                    f"calculation {calculation.id} produced a nonfinite result",
                    fix,
                    file="evidence.json",
                )
            if abs(computed - calculation.result) > calculation.tolerance:
                return problem(
                    f"calculation {calculation.id} result {calculation.result} does not "
                    f"reconcile: the inputs give {computed}",
                    fix,
                    file="evidence.json",
                )
    except (DecimalException, ValueError, OverflowError) as exc:
        return problem(
            f"calculation {calculation.id} could not be evaluated: {exc}",
            fix,
            file="evidence.json",
        )
    return None


def _source_findings(case_path: Path, evidence: Evidence) -> list[Finding]:
    findings: list[Finding] = []
    query_ids = declared_query_ids(case_path)
    for source in evidence.sources:
        try:
            if case_file_digest(case_path, source.artifact) != source.sha256:
                findings.append(
                    Finding(
                        "contract",
                        problem(
                            f"source {source.id}: sha256 does not match {source.artifact}",
                            f"run `shasum -a 256 {source.artifact}` in the case and record "
                            "the hash, after checking that the file is the one you read",
                            file="evidence.json",
                        ),
                    )
                )
        except UnsafeArtifactPathError as exc:
            findings.append(Finding("safety", str(exc)))
        except (OSError, ValueError) as exc:
            findings.extend(
                Finding("contract", entry) for entry in _problem_lines(exc, "evidence.json")
            )
        if source.query_id is not None and source.query_id not in query_ids:
            findings.append(
                Finding(
                    "format",
                    problem(
                        f"source {source.id}: query_id {source.query_id} has no statement",
                        f"add `-- query_id: {source.query_id}` above its statement in queries.sql",
                        file="evidence.json",
                    ),
                )
            )
    return findings


def _marker_findings(
    case_path: Path, evidence: Evidence, *, strict_completion: bool
) -> list[Finding]:
    if not report_path(case_path).exists():
        return []
    try:
        report = case_file(case_path, "report.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        return [Finding("format", entry) for entry in _problem_lines(exc, "report.md")]
    markers = set(re.findall(r"\[C[0-9]+\]", without_accepted_gaps(report)))
    declared = {claim.report_marker for claim in evidence.claims}
    findings = [
        Finding(
            "format",
            problem(
                f"marker {marker} names no claim",
                f"add the claim to evidence.json, or remove {marker}",
                file="report.md",
                line=line_of(report, marker),
            ),
        )
        for marker in sorted(markers - declared)
    ]
    if strict_completion:
        findings.extend(
            Finding(
                "format",
                problem(
                    f"claim marker {marker} is missing",
                    f"add {marker} after the sentence it supports",
                    file="report.md",
                ),
            )
            for marker in sorted(declared - markers)
        )
    return findings


def _review_findings(case_path: Path, *, strict_completion: bool) -> list[Finding]:
    if not review_path(case_path).exists():
        return (
            [
                Finding(
                    "contract",
                    problem(
                        "the independent review is missing",
                        f"ask a new independent reviewer to write it; run "
                        f"`research review-snapshot {case_path.name}` for the hashes it records",
                        file="review.json",
                    ),
                )
            ]
            if strict_completion
            else []
        )
    try:
        review = load_artifact(case_path, "review.json", Review)
    except (OSError, UnicodeError, ValueError) as exc:
        return [
            Finding("contract", entry.replace("<case>", case_path.name))
            for entry in _problem_lines(exc, "review.json")
        ]
    findings: list[Finding] = []
    if review.verdict != "pass":
        findings.append(
            Finding(
                "contract",
                problem(
                    "verdict is blocked",
                    "answer the blocking objections, then ask a new independent reviewer "
                    f"to review again with `research review-snapshot {case_path.name}`",
                    file="review.json",
                ),
            )
        )
    try:
        current_hashes = review_snapshot(case_path)
    except (OSError, UnicodeError, ValueError) as exc:
        return [
            *findings,
            *(Finding("contract", entry) for entry in _problem_lines(exc, "evidence.json")),
        ]
    if set(review.reviewed_hashes) != set(current_hashes):
        findings.append(
            Finding(
                "stale",
                problem(
                    f"{STALE_REVIEW}: its snapshot does not cover exactly the review inputs",
                    f"ask a new independent reviewer to review the current files, with "
                    f"`research review-snapshot {case_path.name}`; never edit a hash yourself",
                ),
            )
        )
    findings.extend(
        Finding(
            "stale",
            problem(
                f"{STALE_REVIEW} for {name}: the reviewer did not see this edit",
                f"ask a new independent reviewer to re-check {name}, with "
                f"`research review-snapshot {case_path.name}`; never edit a hash yourself",
            ),
        )
        for name, digest in current_hashes.items()
        if review.reviewed_hashes.get(name) != digest
    )
    return findings


def _problem_lines(exc: Exception, name: str) -> list[str]:
    """Split a manifest failure into its problems, each naming `name`."""
    text = str(exc)
    if ". Fix: " not in text:
        return [problem(text, "restore a readable file", file=name)]
    return [line if line.startswith(name) else f"{name}: {line}" for line in text.split("\n")]


def _unsafe_artifact_findings(case_path: Path) -> list[Finding]:
    """Check artifact paths in a manifest the schema rejected, because that stays hard."""
    try:
        document = as_table(read_case_json(case_path, "evidence.json"))
    except OSError, UnicodeError, ValueError:
        return []
    sources = document.get("sources")
    entries = cast("list[object]", sources) if isinstance(sources, list) else []
    findings: list[Finding] = []
    for source in entries:
        artifact = as_table(source).get("artifact")
        if isinstance(artifact, str):
            try:
                case_file(case_path, artifact)
            except UnsafeArtifactPathError as exc:
                findings.append(Finding("safety", str(exc)))
            except OSError, ValueError:
                continue
    return findings


def evidence_findings(case_path: Path, *, strict_completion: bool = False) -> list[Finding]:
    """Check evidence integrity and arithmetic, not the truth of prose claims."""
    if not evidence_path(case_path).exists():
        return (
            [
                Finding(
                    "contract",
                    problem(
                        "the evidence manifest is missing",
                        "see `research schema evidence`, or create the case with "
                        "`--rigour decision`",
                        file="evidence.json",
                    ),
                )
            ]
            if strict_completion
            else _review_findings(case_path, strict_completion=False)
        )
    try:
        evidence = load_evidence(case_path)
    except UnsafeArtifactPathError as exc:
        return [Finding("safety", str(exc))]
    except (OSError, UnicodeError, ValueError) as exc:
        return [
            *_unsafe_artifact_findings(case_path),
            *(Finding("contract", entry) for entry in _problem_lines(exc, "evidence.json")),
        ]

    findings = _source_findings(case_path, evidence)
    findings.extend(
        Finding("wrong", error)
        for calculation in evidence.calculations
        if (error := _calculation_error(calculation)) is not None
    )
    findings.extend(_marker_findings(case_path, evidence, strict_completion=strict_completion))
    if strict_completion and (not evidence.sources or not evidence.claims):
        findings.append(
            Finding(
                "contract",
                problem(
                    "no preserved source and claim yet",
                    "preserve the raw result under evidence/, then add it to sources and "
                    "add a claim that cites it",
                    file="evidence.json",
                ),
            )
        )
    if strict_completion:
        findings.extend(
            Finding(
                "format",
                problem(
                    f"coverage for {item.family} is still the scaffold text",
                    f"record whether {item.family} was used, unavailable, or not needed, and why",
                    file="evidence.json",
                    line=line_of(read_text(evidence_path(case_path)), item.family),
                ),
            )
            for item in evidence.coverage
            if item.reason == SCAFFOLD_COVERAGE_REASON
        )
    findings.extend(_review_findings(case_path, strict_completion=strict_completion))
    return findings
