"""One format for every problem an agent can fix: `<file>:<line>: <what>. Fix: <fix>`."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

_FIX = ". Fix: "


def problem(what: str, fix: str, *, file: str | None = None, line: int | None = None) -> str:
    """Render one problem. `file` and `line` are left out when they are not known."""
    where = f"{file}:{line}" if file and line else file
    prefix = f"{where}: " if where else ""
    return f"{prefix}{what.rstrip('.')}{_FIX}{fix.rstrip('.')}."


def is_problem(line: str) -> bool:
    return _FIX in line


def line_of(text: str, needle: str) -> int | None:
    """Return the 1-based line of the first `needle`, or None."""
    position = text.find(needle)
    return text.count("\n", 0, position) + 1 if position >= 0 else None


def _location(error: Mapping[str, Any]) -> str:
    return ".".join(str(part) for part in error["loc"])


def _field(error: Mapping[str, Any]) -> str:
    return str(error["loc"][-1]) if error["loc"] else "the value"


def _shown(value: object) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= 60 else f"{text[:60]}..."


def _what_and_fix(error: Mapping[str, Any]) -> tuple[str, str]:
    where = _location(error)
    field = _field(error)
    context = error.get("ctx", {})
    match error["type"]:
        case "missing":
            return f"{where} is missing", f'add "{field}"'
        case "extra_forbidden":
            return f"{where} is not a known field", f'remove "{field}"'
        case "literal_error":
            return (
                f"{where} is {_shown(error['input'])}",
                f"use {context.get('expected', 'an allowed value')}",
            )
        case "string_too_short" | "too_short":
            return f"{where} is empty", f"fill in {field}"
        case "string_pattern_mismatch":
            return (
                f"{where} is {_shown(error['input'])}",
                f"match the pattern {context.get('pattern')}",
            )
        case _:
            return f"{where}: {error['msg']}", f"correct {field}"


def _line_for_text(text: str, what: str) -> int | None:
    """Find the first word of `what` that the JSON document holds as a string value."""
    for word in re.findall(r"[\w./-]+", what):
        line = line_of(text, f'"{word}"')
        if line is not None:
            return line
    return None


def validation_problems(exc: ValidationError, file: str, text: str | None = None) -> list[str]:
    """Rewrite a pydantic error for `file`. A validator's own message states its fix."""
    problems: list[str] = []
    for error in exc.errors(include_url=False):
        if error["type"] == "value_error":
            detail = error["msg"].removeprefix("Value error, ")
            for entry in detail.split("\n"):
                what, separator, fix = entry.partition(_FIX)
                problems.append(
                    problem(
                        what,
                        fix if separator else f"correct {_field(error)}",
                        file=file,
                        line=_line_for_text(text, what) if text else None,
                    )
                )
            continue
        what, fix = _what_and_fix(error)
        line = line_of(text, f'"{_field(error)}"') if text else None
        problems.append(problem(what, fix, file=file, line=line))
    return problems
