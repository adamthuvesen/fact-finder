"""The evidence contract: `evidence.json` owns evidence, `review.json` owns the challenge.

These checks cover integrity and arithmetic. They cannot prove that a claim is true
or that a reviewer was independent. The reviewer name is an attestation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, DecimalException, localcontext
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self, cast

from pydantic import (
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .feedback import line_of, problem, validation_problems
from .io import read_text
from .layout import as_table, evidence_path, queries_path, report_path, review_path
from .readonly_sql import ReadOnlySql, UnsafeSqlError
from .strict_model import StrictModel

Text = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Number = Annotated[Decimal, Field(allow_inf_nan=False)]
REVIEW_FILES = (
    "brief.md",
    "report.md",
    "queries.sql",
    "source-objects.md",
    "evidence.json",
)
# Words that identify the researcher, a whole client, or nobody. A reviewer made only of
# these names no one. One specific token, such as a task id, is enough to pass.
_GENERIC_REVIEWER_WORDS = frozenset(
    [
        "a",
        "agent",
        "ai",
        "an",
        "anthropic",
        "assigned",
        "assistant",
        "chatgpt",
        "claude",
        "code",
        "codex",
        "fable",
        "gpt",
        "haiku",
        "identifier",
        "independent",
        "llm",
        "main",
        "model",
        "name",
        "not",
        "openai",
        "opus",
        "or",
        "primary",
        "research",
        "researcher",
        "review",
        "reviewer",
        "sonnet",
        "subagent",
        "task",
        "the",
    ]
)
_SELF_REVIEWER_WORDS = frozenset({"me", "self", "tbd", "todo", "unknown"})
SCAFFOLD_COVERAGE_REASON = "Source discovery has not run."


STALE_REVIEW = "review.json is stale"
SNAPSHOT_COMMAND = "`research review-snapshot <case>`"
ACCEPTED_GAPS_START = "<!-- research:accepted-gaps:start -->"
ACCEPTED_GAPS_END = "<!-- research:accepted-gaps:end -->"
ACCEPTED_GAPS_BLOCK = re.compile(
    r"\n?"
    + re.escape(ACCEPTED_GAPS_START)
    + r".*?"
    + re.escape(ACCEPTED_GAPS_END)
    + r"\n?",
    re.DOTALL,
)
# How a validation finding behaves. `safety` and `structure` always block. `answer`, `wrong`,
# and `contract` block a completion check by policy. `stale` blocks only on request, and
# `format` never blocks. See `validation.assess_case`.
FindingKind = Literal[
    "safety", "structure", "answer", "wrong", "contract", "stale", "format"
]


@dataclass(frozen=True)
class Finding:
    kind: FindingKind
    message: str


def reviewer_is_named(reviewer: str) -> bool:
    """Reject self-review and placeholders word by word.

    A real id such as `independent-subagent-challenger` contains generic words without
    being generic, so a substring match would reject it.
    """
    words = set(re.sub(r"[^a-z0-9]+", " ", reviewer.lower()).split())
    return bool(words - _GENERIC_REVIEWER_WORDS) and not words & _SELF_REVIEWER_WORDS


class Source(StrictModel):
    id: Text
    family: Text
    route: Text
    locator: Text
    accessed_at: datetime
    independence_group: Text
    artifact: Text
    sha256: Digest
    query_id: Text | None = None

    @field_validator("accessed_at", mode="before")
    @classmethod
    def iso_timestamp(cls, value: object) -> object:
        if not isinstance(value, str) or "T" not in value:
            raise ValueError(
                "accessed_at is not an ISO datetime. Fix: use a value such as "
                "2026-01-31T09:00:00+00:00"
            )
        return value

    @field_validator("accessed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "accessed_at has no time zone. Fix: add an offset such as +00:00"
            )
        return value


class Coverage(StrictModel):
    family: Text
    status: Literal["used", "unavailable", "not-needed"]
    reason: Text
    consequence: Text


class CalculationInput(StrictModel):
    name: Text
    value: Number
    unit: Text
    source_id: Text

    @field_validator("value", mode="before")
    @classmethod
    def reject_boolean(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("value is a boolean. Fix: use a number")  # noqa: TRY004 - pydantic reports only ValueError
        return value


class Calculation(StrictModel):
    id: Text
    operation: Literal["sum", "difference", "ratio"]
    inputs: list[CalculationInput] = Field(min_length=1)
    result: Number
    unit: Text
    tolerance: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)] = Decimal(0)
    denominator: Text | None = None

    @field_validator("result", "tolerance", mode="before")
    @classmethod
    def reject_boolean(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("value is a boolean. Fix: use a number")  # noqa: TRY004 - pydantic reports only ValueError
        return value

    @model_validator(mode="after")
    def valid_operation(self) -> Self:
        names = [item.name for item in self.inputs]
        if len(names) != len(set(names)):
            raise ValueError(
                f"calculation {self.id} repeats an input name. Fix: name each input once"
            )
        if self.operation in {"difference", "ratio"} and len(self.inputs) != 2:
            raise ValueError(
                f"calculation {self.id}: {self.operation} needs exactly two inputs, "
                f"not {len(self.inputs)}. Fix: use two inputs, or the sum operation"
            )
        if self.operation == "ratio":
            if self.denominator not in names:
                raise ValueError(
                    f"calculation {self.id}: ratio has no named denominator. "
                    f"Fix: set denominator to one of {', '.join(names)}"
                )
            if next(i.value for i in self.inputs if i.name == self.denominator) == 0:
                raise ValueError(
                    f"calculation {self.id}: the ratio denominator is zero. "
                    "Fix: use a nonzero denominator, or remove the calculation"
                )
        elif self.denominator is not None:
            raise ValueError(
                f"calculation {self.id}: denominator applies only to ratio. "
                "Fix: remove denominator"
            )
        if len({item.unit for item in self.inputs}) != 1:
            raise ValueError(
                f"calculation {self.id}: inputs use different units. "
                "Fix: convert the inputs to one unit"
            )
        expected_unit = "ratio" if self.operation == "ratio" else self.inputs[0].unit
        if self.unit != expected_unit:
            raise ValueError(
                f"calculation {self.id}: unit is {self.unit!r}. "
                f"Fix: set unit to {expected_unit!r}"
            )
        return self

    def computed_result(self) -> Decimal:
        if self.operation == "sum":
            return sum((item.value for item in self.inputs), Decimal(0))
        if self.operation == "difference":
            return self.inputs[0].value - self.inputs[1].value
        denominator = next(i.value for i in self.inputs if i.name == self.denominator)
        numerator = next(i.value for i in self.inputs if i.name != self.denominator)
        return numerator / denominator


class Claim(StrictModel):
    id: Annotated[str, Field(pattern=r"^C[1-9][0-9]*$")]
    statement: Text
    kind: Literal["descriptive", "causal"]
    source_ids: list[Text] = Field(min_length=1)
    calculation_ids: list[Text]
    limitations: list[Text]
    status: Literal["supported", "inconclusive"]
    report_marker: Annotated[str, Field(pattern=r"^\[C[1-9][0-9]*\]$")]

    @model_validator(mode="after")
    def matching_marker(self) -> Self:
        if self.report_marker != f"[{self.id}]":
            raise ValueError(
                f"claim {self.id}: report_marker is {self.report_marker}. "
                f"Fix: set report_marker to [{self.id}]"
            )
        if (
            self.kind == "causal" or self.status == "inconclusive"
        ) and not self.limitations:
            raise ValueError(
                f"claim {self.id} is {self.kind} and {self.status} with no limitations. "
                "Fix: add at least one limitation"
            )
        return self


class Evidence(StrictModel):
    schema_version: Literal[1]
    sources: list[Source]
    coverage: list[Coverage]
    claims: list[Claim]
    calculations: list[Calculation]

    @model_validator(mode="after")
    def valid_references(self) -> Self:
        problems = _reference_problems(self)
        if problems:
            raise ValueError("\n".join(problems))
        return self


def _unknown_reference(owner: str, kind: str, missing: str, declared: set[str]) -> str:
    known = ", ".join(sorted(declared))
    only = f"only {known} is declared" if known else f"no {kind} is declared"
    use = f"use {known}, or add" if known else "add"
    return f"{owner} {missing}, but {only}. Fix: {use} {missing} to {kind}s"


def _reference_problems(evidence: Evidence) -> list[str]:
    """List every broken reference at once, so one pass can fix them all."""
    problems = [
        f"{name} id {item} appears more than once. Fix: give each entry its own id"
        for name, items in (
            ("source", evidence.sources),
            ("claim", evidence.claims),
            ("calculation", evidence.calculations),
        )
        for item, count in Counter(entry.id for entry in items).items()
        if count > 1
    ]
    problems.extend(
        f"coverage lists {family} more than once. Fix: keep one entry for {family}"
        for family, count in Counter(i.family for i in evidence.coverage).items()
        if count > 1
    )
    source_ids = {item.id for item in evidence.sources}
    calculation_ids = {item.id for item in evidence.calculations}
    used_families = {item.family for item in evidence.sources}
    declared_used = {item.family for item in evidence.coverage if item.status == "used"}
    problems.extend(
        f'sources use family {family}, but coverage does not mark it used. Fix: set its coverage status to "used"'
        for family in sorted(used_families - declared_used)
    )
    problems.extend(
        f"coverage marks {family} used, but no source has that family. Fix: add its source, or change the status"
        for family in sorted(declared_used - used_families)
    )
    for calculation in evidence.calculations:
        problems.extend(
            _unknown_reference(
                f"calculation {calculation.id} uses",
                "source",
                item.source_id,
                source_ids,
            )
            for item in calculation.inputs
            if item.source_id not in source_ids
        )
    for claim in evidence.claims:
        problems.extend(
            _unknown_reference(f"claim {claim.id} cites", "source", missing, source_ids)
            for missing in claim.source_ids
            if missing not in source_ids
        )
        problems.extend(
            _unknown_reference(
                f"claim {claim.id} cites", "calculation", missing, calculation_ids
            )
            for missing in claim.calculation_ids
            if missing not in calculation_ids
        )
        through_calculations = {
            item.source_id
            for calculation in evidence.calculations
            if calculation.id in claim.calculation_ids
            for item in calculation.inputs
        }
        problems.extend(
            f"claim {claim.id} uses a calculation that reads {source}, but its source_ids omit it. Fix: add {source} to source_ids"
            for source in sorted(through_calculations - set(claim.source_ids))
        )
    return problems


class Objection(StrictModel):
    objection: Text
    disposition: Literal["resolved", "narrowed", "inconclusive", "blocking"]
    resolution: Text


class Review(StrictModel):
    """Reviewer identity is an attestation, not proof of an independent session."""

    schema_version: Literal[1]
    reviewer: Text
    reviewed_hashes: dict[Text, Digest]
    objections: list[Objection]
    strongest_alternative: Text
    weakest_claim: Text
    fragile_dependency: Text
    verdict: Literal["pass", "blocked"]

    @field_validator("reviewer")
    @classmethod
    def named_reviewer(cls, value: str) -> str:
        if not reviewer_is_named(value):
            raise ValueError(
                f"reviewer {value!r} names no independent reviewer. "
                "Fix: record the subagent name or task id"
            )
        return value

    @model_validator(mode="after")
    def complete_snapshot(self) -> Self:
        missing = set(REVIEW_FILES) - self.reviewed_hashes.keys()
        if missing:
            raise ValueError(
                f"reviewed_hashes omits {', '.join(sorted(missing))}. "
                f"Fix: ask a new independent reviewer to review the current files, and to "
                f"record the hashes {SNAPSHOT_COMMAND} prints; never fill in a hash yourself"
            )
        if self.verdict == "pass" and any(
            item.disposition == "blocking" for item in self.objections
        ):
            raise ValueError(
                "verdict is pass with a blocking objection. "
                'Fix: resolve the objection, or set verdict to "blocked"'
            )
        return self


def evidence_template(allowed_sources: list[str]) -> str:
    evidence = Evidence(
        schema_version=1,
        sources=[],
        coverage=[
            Coverage(
                family=family,
                status="unavailable",
                reason=SCAFFOLD_COVERAGE_REASON,
                consequence="No evidence from this source is available yet.",
            )
            for family in dict.fromkeys(allowed_sources)
        ],
        claims=[],
        calculations=[],
    )
    return evidence.model_dump_json(indent=2) + "\n"


def declared_query_ids(case_path: Path) -> frozenset[str]:
    """Return the ids `queries.sql` declares, or none when it is missing, unreadable, or unsafe."""
    path = queries_path(case_path)
    if not path.exists():
        return frozenset()
    try:
        return ReadOnlySql.parse(read_text(path)).query_ids
    except (OSError, UnicodeError, UnsafeSqlError):
        return frozenset()


class UnsafeArtifactPathError(ValueError):
    """Raised when an artifact path would read outside the case. This is safety, not rigour."""


def _case_file(case_path: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    # `./x` and `a//b` would hash the same file under a second name.
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "\\" in name
        or relative.as_posix() != name
    ):
        raise UnsafeArtifactPathError(
            problem(
                f"unsafe case artifact path {name}",
                "use a plain relative path inside the case, such as evidence/data.csv",
                file="evidence.json",
            )
        )
    path = (case_path / name).resolve()
    if not path.is_relative_to(case_path.resolve()):
        raise UnsafeArtifactPathError(
            problem(
                f"artifact {name} escapes the case directory",
                "copy the file into the case and cite the copy",
                file="evidence.json",
            )
        )
    if not path.is_file():
        raise ValueError(
            problem(
                f"artifact {name} does not exist",
                f"save it at {name} in the case, or correct the path",
            )
        )
    return path


def without_accepted_gaps(report: str) -> str:
    """Remove the block `--accept` writes. It is not part of what a reviewer judged."""
    return ACCEPTED_GAPS_BLOCK.sub("", report)


def _digest(case_path: Path, name: str) -> str:
    content = _case_file(case_path, name).read_bytes()
    if name == "report.md" and ACCEPTED_GAPS_START.encode() in content:
        content = without_accepted_gaps(content.decode("utf-8")).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(
                problem(f"duplicate JSON key {key}", f'keep one "{key}" in this object')
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(problem(f"non-finite JSON number {value}", "use a finite number"))


def _read_json(case_path: Path, name: str) -> object:
    try:
        return json.loads(
            _case_file(case_path, name).read_text(encoding="utf-8"),
            parse_float=Decimal,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_keys,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            problem(
                f"not valid JSON: {exc.msg}",
                "correct the JSON syntax",
                file=name,
                line=exc.lineno,
            )
        ) from exc
    except RecursionError as exc:
        raise ValueError(
            problem("nested too deeply", "flatten the document", file=name)
        ) from exc


def _load_artifact[ModelT: StrictModel](
    case_path: Path, name: str, model: type[ModelT]
) -> ModelT:
    """Parse one manifest. Any failure is a ValueError with one fixable problem per line."""
    document = _read_json(case_path, name)
    try:
        return model.model_validate(document)
    except ValidationError as exc:
        text = read_text(case_path / name)
        raise ValueError("\n".join(validation_problems(exc, name, text))) from exc


def load_evidence(case_path: Path) -> Evidence:
    return _load_artifact(case_path, evidence_path(case_path).name, Evidence)


def review_snapshot(case_path: Path) -> dict[str, str]:
    """Hash the current review inputs without creating a reviewer attestation."""
    evidence = load_evidence(case_path)
    names = set(REVIEW_FILES) | {source.artifact for source in evidence.sources}
    return {name: _digest(case_path, name) for name in sorted(names)}


def _calculation_error(calculation: Calculation) -> str | None:
    fix = "recompute result and record the correct value, or correct the inputs"
    values = [
        *(item.value for item in calculation.inputs),
        calculation.result,
        calculation.tolerance,
    ]
    exponents = [
        exponent
        for value in values
        if isinstance(exponent := value.as_tuple().exponent, int)
    ]
    try:
        with localcontext() as context:
            context.prec = max(
                28,
                max(value.adjusted() for value in values)
                - min(exponents)
                + len(values)
                + 2,
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
            if _digest(case_path, source.artifact) != source.sha256:
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
                Finding("contract", entry)
                for entry in _problem_lines(exc, "evidence.json")
            )
        if source.query_id is not None and source.query_id not in query_ids:
            findings.append(
                Finding(
                    "format",
                    problem(
                        f"source {source.id}: query_id {source.query_id} has no statement",
                        f"add `-- query_id: {source.query_id}` above its statement in "
                        "queries.sql",
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
        report = _case_file(case_path, "report.md").read_text(encoding="utf-8")
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
        review = _load_artifact(case_path, "review.json", Review)
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
            *(
                Finding("contract", entry)
                for entry in _problem_lines(exc, "evidence.json")
            ),
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
    return [
        line if line.startswith(name) else f"{name}: {line}"
        for line in text.split("\n")
    ]


def _unsafe_artifact_findings(case_path: Path) -> list[Finding]:
    """Check artifact paths in a manifest the schema rejected, because that stays hard."""
    try:
        document = as_table(_read_json(case_path, "evidence.json"))
    except (OSError, UnicodeError, ValueError):
        return []
    sources = document.get("sources")
    entries = cast("list[object]", sources) if isinstance(sources, list) else []
    findings: list[Finding] = []
    for source in entries:
        artifact = as_table(source).get("artifact")
        if isinstance(artifact, str):
            try:
                _case_file(case_path, artifact)
            except UnsafeArtifactPathError as exc:
                findings.append(Finding("safety", str(exc)))
            except (OSError, ValueError):
                continue
    return findings


def evidence_findings(
    case_path: Path, *, strict_completion: bool = False
) -> list[Finding]:
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
            *(
                Finding("contract", entry)
                for entry in _problem_lines(exc, "evidence.json")
            ),
        ]

    findings = _source_findings(case_path, evidence)
    findings.extend(
        Finding("wrong", error)
        for calculation in evidence.calculations
        if (error := _calculation_error(calculation)) is not None
    )
    findings.extend(
        _marker_findings(case_path, evidence, strict_completion=strict_completion)
    )
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
                    f"record whether {item.family} was used, unavailable, or not needed, "
                    "and why",
                    file="evidence.json",
                    line=line_of(read_text(evidence_path(case_path)), item.family),
                ),
            )
            for item in evidence.coverage
            if item.reason == SCAFFOLD_COVERAGE_REASON
        )
    findings.extend(_review_findings(case_path, strict_completion=strict_completion))
    return findings
