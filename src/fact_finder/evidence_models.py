"""The evidence contract's models: `evidence.json` owns evidence, `review.json` owns the challenge.

These checks cover integrity and arithmetic. They cannot prove that a claim is true
or that a reviewer was independent. The reviewer name is an attestation.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

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
SNAPSHOT_COMMAND = "`research review-snapshot <case>`"


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
            raise ValueError("accessed_at has no time zone. Fix: add an offset such as +00:00")
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
                f"calculation {self.id}: denominator applies only to ratio. Fix: remove denominator"
            )
        if len({item.unit for item in self.inputs}) != 1:
            raise ValueError(
                f"calculation {self.id}: inputs use different units. "
                "Fix: convert the inputs to one unit"
            )
        expected_unit = "ratio" if self.operation == "ratio" else self.inputs[0].unit
        if self.unit != expected_unit:
            raise ValueError(
                f"calculation {self.id}: unit is {self.unit!r}. Fix: set unit to {expected_unit!r}"
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
        if (self.kind == "causal" or self.status == "inconclusive") and not self.limitations:
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
            _unknown_reference(f"claim {claim.id} cites", "calculation", missing, calculation_ids)
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
