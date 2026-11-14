"""Short forms of the validators, for tests that only need the messages."""

from __future__ import annotations

from pathlib import Path

from fact_finder.evidence_findings import evidence_findings
from fact_finder.validation import assess_case


def validate_case(case_path: Path, *, strict_completion: bool = False) -> list[str]:
    return assess_case(case_path, strict_completion=strict_completion).errors


def validate_evidence(case_path: Path, *, strict_completion: bool = False) -> list[str]:
    return [
        finding.message
        for finding in evidence_findings(case_path, strict_completion=strict_completion)
    ]
