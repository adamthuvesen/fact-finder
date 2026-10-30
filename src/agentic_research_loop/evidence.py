"""The evidence contract: `evidence.json` owns evidence, `review.json` owns the challenge.

These checks cover integrity and arithmetic. They cannot prove that a claim is true
or that a reviewer was independent. The reviewer name is an attestation.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, DecimalException, localcontext
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import (
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .io import read_text
from .layout import evidence_path, queries_path, report_path, review_path
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
            raise ValueError("accessed_at must be an ISO datetime with a time zone")
        return value

    @field_validator("accessed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("accessed_at must include a time zone")
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
            raise ValueError("numeric inputs cannot be booleans")  # noqa: TRY004 - pydantic reports only ValueError
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
            raise ValueError("numeric values cannot be booleans")  # noqa: TRY004 - pydantic reports only ValueError
        return value

    @model_validator(mode="after")
    def valid_operation(self) -> Self:
        names = [item.name for item in self.inputs]
        if len(names) != len(set(names)):
            raise ValueError("calculation input names must be unique")
        if self.operation in {"difference", "ratio"} and len(self.inputs) != 2:
            raise ValueError(f"{self.operation} requires exactly two inputs")
        if self.operation == "ratio":
            if self.denominator not in names:
                raise ValueError("ratio requires a named denominator input")
            if next(i.value for i in self.inputs if i.name == self.denominator) == 0:
                raise ValueError("ratio denominator cannot be zero")
        elif self.denominator is not None:
            raise ValueError("denominator is only valid for ratio calculations")
        if len({item.unit for item in self.inputs}) != 1:
            raise ValueError("calculation inputs must use the same unit")
        expected_unit = "ratio" if self.operation == "ratio" else self.inputs[0].unit
        if self.unit != expected_unit:
            raise ValueError(f"calculation result unit must be {expected_unit!r}")
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
            raise ValueError("report_marker must match the claim id")
        if (
            self.kind == "causal" or self.status == "inconclusive"
        ) and not self.limitations:
            raise ValueError("causal and inconclusive claims need explicit limitations")
        return self


class Evidence(StrictModel):
    schema_version: Literal[1]
    sources: list[Source]
    coverage: list[Coverage]
    claims: list[Claim]
    calculations: list[Calculation]

    @model_validator(mode="after")
    def valid_references(self) -> Self:
        for name in ("sources", "claims", "calculations"):
            ids = [item.id for item in getattr(self, name)]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {name} ids")
        families = [item.family for item in self.coverage]
        if len(families) != len(set(families)):
            raise ValueError("duplicate coverage families")
        source_ids = {item.id for item in self.sources}
        calculation_ids = {item.id for item in self.calculations}
        used_families = {item.family for item in self.sources}
        declared_used = {item.family for item in self.coverage if item.status == "used"}
        if used_families != declared_used:
            raise ValueError(
                "used coverage families must exactly match source families"
            )
        for calculation in self.calculations:
            for item in calculation.inputs:
                if item.source_id not in source_ids:
                    raise ValueError(
                        f"{calculation.id}: unknown source {item.source_id}"
                    )
        for claim in self.claims:
            if not set(claim.source_ids) <= source_ids:
                raise ValueError(f"{claim.id}: unknown source reference")
            if not set(claim.calculation_ids) <= calculation_ids:
                raise ValueError(f"{claim.id}: unknown calculation reference")
            referenced_sources = {
                item.source_id
                for calculation in self.calculations
                if calculation.id in claim.calculation_ids
                for item in calculation.inputs
            }
            if not referenced_sources <= set(claim.source_ids):
                raise ValueError(
                    f"{claim.id}: calculation sources missing from source_ids"
                )
        return self


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
                f"reviewer {value!r} names no independent reviewer; "
                "record the subagent name or task id"
            )
        return value

    @model_validator(mode="after")
    def complete_snapshot(self) -> Self:
        missing = set(REVIEW_FILES) - self.reviewed_hashes.keys()
        if missing:
            raise ValueError("reviewed_hashes missing: " + ", ".join(sorted(missing)))
        if self.verdict == "pass" and any(
            item.disposition == "blocking" for item in self.objections
        ):
            raise ValueError("passing review cannot contain blocking objections")
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
    """Return the ids `queries.sql` declares, or none when it is missing or unsafe."""
    path = queries_path(case_path)
    if not path.exists():
        return frozenset()
    try:
        return ReadOnlySql.parse(read_text(path)).query_ids
    except UnsafeSqlError:
        return frozenset()


def _case_file(case_path: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    # `./x` and `a//b` would hash the same file under a second name.
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "\\" in name
        or relative.as_posix() != name
    ):
        raise ValueError(f"unsafe case artifact path: {name}")
    path = (case_path / name).resolve()
    if not path.is_relative_to(case_path.resolve()):
        raise ValueError(f"case artifact escapes case directory: {name}")
    if not path.is_file():
        raise ValueError(f"missing case artifact: {name}")
    return path


def _digest(case_path: Path, name: str) -> str:
    return hashlib.sha256(_case_file(case_path, name).read_bytes()).hexdigest()


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _read_json(case_path: Path, name: str) -> object:
    try:
        return json.loads(
            _case_file(case_path, name).read_text(encoding="utf-8"),
            parse_float=Decimal,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_keys,
        )
    except RecursionError as exc:
        raise ValueError(f"{name} is nested too deeply") from exc


def load_evidence(case_path: Path) -> Evidence:
    return Evidence.model_validate(_read_json(case_path, evidence_path(case_path).name))


def review_snapshot(case_path: Path) -> dict[str, str]:
    """Hash the current review inputs without creating a reviewer attestation."""
    evidence = load_evidence(case_path)
    names = set(REVIEW_FILES) | {source.artifact for source in evidence.sources}
    return {name: _digest(case_path, name) for name in sorted(names)}


def _calculation_error(calculation: Calculation) -> str | None:
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
                return f"{calculation.id}: calculation produced a nonfinite result"
            if abs(computed - calculation.result) > calculation.tolerance:
                return f"{calculation.id}: calculation result does not reconcile"
    except (DecimalException, ValueError, OverflowError) as exc:
        return f"{calculation.id}: calculation could not be evaluated: {exc}"
    return None


def _source_errors(case_path: Path, evidence: Evidence) -> list[str]:
    errors: list[str] = []
    query_ids = declared_query_ids(case_path)
    for source in evidence.sources:
        try:
            if _digest(case_path, source.artifact) != source.sha256:
                errors.append(
                    f"{source.id}: artifact sha256 mismatch: {source.artifact}"
                )
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
        if source.query_id is not None and source.query_id not in query_ids:
            errors.append(
                f"{source.id}: query_id {source.query_id} has no "
                f"`-- query_id: {source.query_id}` line in queries.sql"
            )
    return errors


def _marker_errors(
    case_path: Path, evidence: Evidence, *, strict_completion: bool
) -> list[str]:
    if not report_path(case_path).exists():
        return ["Missing report.md for evidence claims"] if strict_completion else []
    try:
        report = _case_file(case_path, "report.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        return [str(exc)]
    markers = set(re.findall(r"\[C[0-9]+\]", report))
    declared = {claim.report_marker for claim in evidence.claims}
    errors = [
        f"report.md references unknown claim {marker}"
        for marker in sorted(markers - declared)
    ]
    if strict_completion:
        errors.extend(
            f"report.md is missing claim marker {marker}"
            for marker in sorted(declared - markers)
        )
    return errors


def _review_errors(case_path: Path, *, strict_completion: bool) -> list[str]:
    if not review_path(case_path).exists():
        return (
            ["Missing review.json: obtain an independent final challenge"]
            if strict_completion
            else []
        )
    try:
        review = Review.model_validate(_read_json(case_path, "review.json"))
        current_hashes = review_snapshot(case_path)
    except (OSError, UnicodeError, ValueError, ValidationError) as exc:
        return [f"Invalid review.json: {exc}"]
    errors: list[str] = []
    if set(review.reviewed_hashes) != set(current_hashes):
        errors.append("review.json snapshot must include exactly all review inputs")
    errors.extend(
        f"review.json is stale for {name}"
        for name, digest in current_hashes.items()
        if review.reviewed_hashes.get(name) != digest
    )
    if strict_completion and review.verdict != "pass":
        errors.append("review.json verdict is blocked")
    return errors


def validate_evidence(case_path: Path, *, strict_completion: bool = False) -> list[str]:
    """Check evidence integrity and arithmetic, not the truth of prose claims."""
    if not evidence_path(case_path).exists():
        return ["Missing evidence.json"] if strict_completion else []
    try:
        evidence = load_evidence(case_path)
    except (OSError, UnicodeError, ValueError, ValidationError) as exc:
        return [f"Invalid evidence.json: {exc}"]

    errors = _source_errors(case_path, evidence)
    errors.extend(
        error
        for calculation in evidence.calculations
        if (error := _calculation_error(calculation)) is not None
    )
    errors.extend(
        _marker_errors(case_path, evidence, strict_completion=strict_completion)
    )
    if strict_completion and (not evidence.sources or not evidence.claims):
        errors.append("evidence.json needs at least one preserved source and claim")
    if strict_completion:
        errors.extend(
            f"evidence.json coverage for {item.family} is still the scaffold text"
            for item in evidence.coverage
            if item.reason == SCAFFOLD_COVERAGE_REASON
        )
    errors.extend(_review_errors(case_path, strict_completion=strict_completion))
    return errors
