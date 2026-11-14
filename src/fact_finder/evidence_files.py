"""Read a case's evidence artifacts safely: inside the case, strict JSON, and hashed for review."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from .evidence_models import REVIEW_FILES, Evidence
from .feedback import problem, validation_problems
from .io import read_text
from .layout import evidence_path, queries_path
from .readonly_sql import ReadOnlySql, UnsafeSqlError
from .strict_model import StrictModel

ACCEPTED_GAPS_START = "<!-- research:accepted-gaps:start -->"
ACCEPTED_GAPS_END = "<!-- research:accepted-gaps:end -->"
ACCEPTED_GAPS_BLOCK = re.compile(
    r"\n?" + re.escape(ACCEPTED_GAPS_START) + r".*?" + re.escape(ACCEPTED_GAPS_END) + r"\n?",
    re.DOTALL,
)


def declared_query_ids(case_path: Path) -> frozenset[str]:
    """Return the ids `queries.sql` declares, or none when it is missing, unreadable, or unsafe."""
    path = queries_path(case_path)
    if not path.exists():
        return frozenset()
    try:
        return ReadOnlySql.parse(read_text(path)).query_ids
    except OSError, UnicodeError, UnsafeSqlError:
        return frozenset()


class UnsafeArtifactPathError(ValueError):
    """Raised when an artifact path would read outside the case. This is safety, not rigour."""


def case_file(case_path: Path, name: str) -> Path:
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


def case_file_digest(case_path: Path, name: str) -> str:
    content = case_file(case_path, name).read_bytes()
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


def read_case_json(case_path: Path, name: str) -> object:
    try:
        return json.loads(
            case_file(case_path, name).read_text(encoding="utf-8"),
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
        raise ValueError(problem("nested too deeply", "flatten the document", file=name)) from exc


def load_artifact[ModelT: StrictModel](case_path: Path, name: str, model: type[ModelT]) -> ModelT:
    """Parse one manifest. Any failure is a ValueError with one fixable problem per line."""
    document = read_case_json(case_path, name)
    try:
        return model.model_validate(document)
    except ValidationError as exc:
        text = read_text(case_path / name)
        raise ValueError("\n".join(validation_problems(exc, name, text))) from exc


def load_evidence(case_path: Path) -> Evidence:
    return load_artifact(case_path, evidence_path(case_path).name, Evidence)


def review_snapshot(case_path: Path) -> dict[str, str]:
    """Hash the current review inputs without creating a reviewer attestation."""
    evidence = load_evidence(case_path)
    names = set(REVIEW_FILES) | {source.artifact for source in evidence.sources}
    return {name: case_file_digest(case_path, name) for name in sorted(names)}
