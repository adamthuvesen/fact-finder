"""A person's recorded overrides of rigour checks, kept in a case's overrides.json."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, ValidationError

from .feedback import validation_problems
from .io import read_text
from .strict_model import StrictModel

OVERRIDES_FILE = "overrides.json"


class Override(StrictModel):
    """A person's recorded decision to accept what a rigour check would block."""

    reason: str = Field(min_length=1)
    accepted_at: str
    accepted: list[str]


class OverridesFile(StrictModel):
    overrides: list[Override]


def load_overrides(case_path: Path) -> list[Override]:
    path = case_path / OVERRIDES_FILE
    if not path.exists():
        return []
    try:
        return OverridesFile.model_validate_json(read_text(path)).overrides
    except ValidationError as exc:
        raise ValueError(
            "\n".join(validation_problems(exc, OVERRIDES_FILE, read_text(path)))
        ) from exc


def one_line(text: str, limit: int = 160) -> str:
    """Shorten a finding for a label: what was accepted, without how to fix it."""
    flat = " ".join(text.split(". Fix: ", maxsplit=1)[0].split())
    return flat if len(flat) <= limit else f"{flat[:limit]}..."
