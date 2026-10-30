"""The source registry: what each source is and how it stays read-only.

Only web search is built in. Everything else comes from `config/sources.json`,
which `research source enable` writes. The file is read on demand, so a malformed
file produces one clean error instead of failing at import.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, ValidationError, model_validator

from .io import read_text
from .strict_model import StrictModel

USER_SOURCES_FILE = "config/sources.json"
LOCAL_FAMILY = "local"
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

Text = Annotated[str, Field(min_length=1)]
Transport = Literal["http-oauth", "stdio", "cli", "native"]
Client = Literal["claude", "cursor", "codex"]
Category = Literal[
    "built-in",
    "work-context",
    "warehouse",
    "product-analytics",
    "observability-revenue",
]
# Config can prove the first four. The last three live outside any file this repo
# can read, so `research doctor` reports them as declared, not checked.
Mechanism = Literal[
    "url_suffix",
    "server_flag",
    "arg_absent",
    "statement_allowlist",
    "credential_scope",
    "credential",
    "native",
]
CONFIG_CHECKED: frozenset[Mechanism] = frozenset(
    {"url_suffix", "server_flag", "arg_absent", "statement_allowlist"}
)


class SourceConfigError(ValueError):
    """Raised when `config/sources.json` or a bundle file is malformed."""


class ReadOnlyControl(StrictModel):
    """The control that keeps a source read-only, from a closed set of mechanisms."""

    mechanism: Mechanism
    detail: Text


class SourceSpec(StrictModel):
    display_name: Text
    category: Category
    transport: Transport
    read_only_control: ReadOnlyControl
    plan_line: Text
    notes: Text
    sql_backed: bool = False


class OAuthClient(StrictModel):
    client_id: Text
    callback_port: int


class ServerDefinition(StrictModel):
    """One MCP server. Client config shapes are generated from it."""

    server_name: Annotated[str, Field(pattern=NAME_PATTERN.pattern)]
    url: Text | None = None
    command: Text | None = None
    args: list[str] = Field(default_factory=list[str])
    oauth: OAuthClient | None = None
    write_tools: list[Text] = Field(default_factory=list[str])
    support_files: list[Text] = Field(default_factory=list[str])
    placeholders: list[Text] = Field(default_factory=list[str])

    @model_validator(mode="after")
    def one_transport(self) -> Self:
        if (self.url is None) == (self.command is None):
            raise ValueError("define exactly one of url or command")
        return self


class Wiring(StrictModel):
    """What the engine added to client files for one source, so disable removes only it."""

    server_name: Text
    clients: list[Client]
    claude_deny: list[str] = Field(default_factory=list[str])
    cursor_deny: list[str] = Field(default_factory=list[str])


class SourcesFile(StrictModel):
    sources: dict[str, SourceSpec]
    wiring: dict[str, Wiring] = Field(default_factory=dict[str, Wiring])


WEB_SEARCH = "web-search"
BUILTIN_SOURCES = {
    WEB_SEARCH: SourceSpec(
        display_name="Web",
        category="built-in",
        transport="native",
        read_only_control=ReadOnlyControl(
            mechanism="native", detail="built-in read-only search tool"
        ),
        plan_line="Web tools for external context and public changes.",
        notes="Search for external context, public incidents, competitor moves, and platform changes. Read-only.",
    ),
}


def _parse_document(text: str, label: str) -> SourcesFile:
    try:
        parsed = SourcesFile.model_validate_json(text)
    except ValidationError as exc:
        problems = "; ".join(
            ": ".join(filter(None, (".".join(map(str, error["loc"])), error["msg"])))
            for error in exc.errors(include_url=False, include_input=False)
        )
        raise SourceConfigError(f"{label} is invalid: {problems}") from exc
    for name in parsed.sources:
        if not NAME_PATTERN.match(name):
            raise SourceConfigError(
                f"{label}: source name {name!r} must use lowercase letters, digits, "
                "'-' or '_', and start with a letter or digit."
            )
    return parsed


def parse_sources_file(text: str, label: str) -> dict[str, SourceSpec]:
    """Parse a `{"sources": {name: spec}}` document, naming `label` in any error."""
    return _parse_document(text, label).sources


def user_sources_path(repo_root: Path) -> Path:
    return repo_root / USER_SOURCES_FILE


def load_sources_file(repo_root: Path) -> SourcesFile:
    path = user_sources_path(repo_root)
    if not path.exists():
        return SourcesFile(sources={})
    document = _parse_document(read_text(path), USER_SOURCES_FILE)
    for name in document.sources:
        if name in BUILTIN_SOURCES:
            raise SourceConfigError(
                f"{USER_SOURCES_FILE} redefines built-in source {name!r}; "
                "choose a different name."
            )
    return document


def render_sources_file(document: SourcesFile) -> str:
    return (
        json.dumps(
            document.model_dump(exclude_defaults=True), indent=2, ensure_ascii=False
        )
        + "\n"
    )


def load_registry(repo_root: Path) -> dict[str, SourceSpec]:
    return {**BUILTIN_SOURCES, **load_sources_file(repo_root).sources}


SENSITIVE_PATH_PARTS = frozenset(
    {".aws", ".azure", ".config", ".docker", ".gnupg", ".kube", ".ssh", "Library"}
)


def _local_context_lines(raw_path: str) -> list[str]:
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Local context path does not exist: {path}")
    lines = [f"Local context folder: {path}"]
    if path in (Path(path.anchor), Path.home().resolve()):
        lines.append(
            "Local context note: Broad path attached intentionally; avoid unrelated private files."
        )
    elif SENSITIVE_PATH_PARTS.intersection(path.parts):
        lines.append(
            "Local context note: Sensitive-looking path attached; avoid secrets and credentials."
        )
    return lines


def source_constraints(
    registry: dict[str, SourceSpec],
    names: list[str],
    *,
    hints: dict[str, str] | None = None,
    local_context_paths: list[str] | None = None,
) -> list[str]:
    """Render the sources a case may use, one per line.

    The read-only policy is not repeated here. The brief and the goal contract each
    state it in their own prose.
    """
    hints = hints or {}
    unknown = sorted(set(names) - registry.keys())
    if unknown:
        raise ValueError(
            f"Unknown source: {', '.join(unknown)}. "
            f"Valid sources: {', '.join(sorted(registry))}"
        )
    unused_hints = sorted(set(hints) - set(names))
    if unused_hints:
        raise ValueError(
            "Source hints require the source to be allowed: " + ", ".join(unused_hints)
        )
    plan_lines = [registry[name].plan_line for name in names]
    hint_lines = [
        f"{registry[name].display_name} focus: {hints[name]}"
        for name in names
        if name in hints
    ]
    local_lines = [
        line
        for path in local_context_paths or []
        for line in _local_context_lines(path)
    ]
    return [*plan_lines, *hint_lines, *local_lines]
