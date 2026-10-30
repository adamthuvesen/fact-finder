from __future__ import annotations

import re
import tomllib
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from .io import read_text

PROJECT_NAME = "agentic-research-loop"


def as_table(value: object) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _project_settings(pyproject_path: Path) -> dict[str, Any] | None:
    """Return the engine settings table, or None if this is not an engine project."""
    try:
        payload = tomllib.loads(read_text(pyproject_path))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{pyproject_path} is not valid TOML: {exc}") from exc
    tool = as_table(payload.get("tool"))
    if PROJECT_NAME in tool:
        return as_table(tool[PROJECT_NAME])
    return {} if as_table(payload.get("project")).get("name") == PROJECT_NAME else None


def find_repo_root(start: Path | None = None) -> Path:
    """Find this repo, or a consumer repo that declares `[tool.agentic-research-loop]`."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        pyproject_path = candidate / "pyproject.toml"
        if pyproject_path.exists() and _project_settings(pyproject_path) is not None:
            return candidate
    raise FileNotFoundError(
        f"Could not find a project root from {current}. Run from the {PROJECT_NAME} "
        f"repo, or add a [tool.{PROJECT_NAME}] table to your pyproject.toml."
    )


def project_setting(repo_root: Path, name: str) -> str | None:
    """Read one string value from `[tool.agentic-research-loop]`."""
    settings = _project_settings(repo_root / "pyproject.toml") or {}
    value = settings.get(name)
    return value if isinstance(value, str) else None


def local_today() -> date:
    return datetime.now().astimezone().date()


MAX_SLUG_LENGTH = 60

STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "can",
        "could",
        "of",
        "in",
        "to",
        "for",
        "with",
        "on",
        "at",
        "by",
        "from",
        "up",
        "about",
        "into",
        "over",
        "after",
        "before",
        "between",
        "under",
        "during",
        "and",
        "but",
        "or",
        "not",
        "so",
        "yet",
        "both",
        "either",
        "neither",
        "each",
        "every",
        "all",
        "any",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "only",
        "same",
        "than",
        "too",
        "very",
        "just",
        "because",
        "as",
        "until",
        "while",
        "how",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "that",
        "these",
        "those",
        "this",
        "it",
        "its",
        "my",
        "our",
        "your",
        "their",
        "his",
        "her",
        "we",
        "they",
        "he",
        "she",
        "i",
        "me",
        "us",
        "them",
        "last",
        "many",
    }
)


def slugify(value: str, *, max_length: int = MAX_SLUG_LENGTH) -> str:
    words = re.findall(r"[a-z0-9]+", value.lower())
    content = [w for w in words if w not in STOP_WORDS]
    if not content:
        content = words
    unique = list(dict.fromkeys(content))
    slug = "-".join(unique)
    if not slug:
        raise ValueError("Slug must contain at least one letter or number.")
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0]
    if not slug:
        slug = "-".join(unique)[:max_length]
    return slug


def case_slug(question_or_slug: str, today: date | None = None) -> str:
    return f"{(today or local_today()).isoformat()}-{slugify(question_or_slug)}"


def research_dir(repo_root: Path) -> Path:
    return repo_root / "research"


def case_dir(repo_root: Path, case_id: str) -> Path:
    return research_dir(repo_root) / case_id


def brief_path(case_path: Path) -> Path:
    return case_path / "brief.md"


def notes_path(case_path: Path) -> Path:
    return case_path / "notes.md"


def report_path(case_path: Path) -> Path:
    return case_path / "report.md"


def queries_path(case_path: Path) -> Path:
    return case_path / "queries.sql"


def source_objects_path(case_path: Path) -> Path:
    return case_path / "source-objects.md"


def plan_path(case_path: Path) -> Path:
    return case_path / "plan.md"


def evidence_path(case_path: Path) -> Path:
    return case_path / "evidence.json"


def review_path(case_path: Path) -> Path:
    return case_path / "review.json"
