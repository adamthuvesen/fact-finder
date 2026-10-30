from __future__ import annotations

import sys
from pathlib import Path

RECOGNIZED_FILES = {
    "brief.md": "brief",
    "plan.md": "plan",
    "notes.md": "notes",
    "report.md": "report",
    "queries.sql": "queries",
    "source-objects.md": "source_objects",
}


def load_from_spec_dir(path: Path) -> dict[str, str]:
    """Load pre-authored case artifacts from a directory, keyed by artifact.

    Raises `FileNotFoundError` if `path` is not a directory, and `ValueError` if a
    recognized file is not UTF-8. Warns on stderr when no recognized file exists.
    """
    if not path.is_dir():
        raise FileNotFoundError(f"--from-spec path is not a directory: {path}")

    loaded: dict[str, str] = {}
    for name, key in RECOGNIZED_FILES.items():
        file_path = path / name
        if not file_path.exists():
            continue
        try:
            loaded[key] = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"--from-spec file is not valid UTF-8: {file_path}"
            ) from exc

    if not loaded:
        sys.stderr.write(
            f"warning: --from-spec directory {path} has no recognized artifact. "
            f"Using default templates. Recognized: {', '.join(RECOGNIZED_FILES)}.\n"
        )
    return loaded


def replace_markdown_section(text: str, heading: str, body: str) -> str:
    """Replace the body of a `## <heading>` section, appending it if absent.

    The section runs from its header to the next `## ` header or end of file.
    When the heading appears more than once the first is replaced and the rest
    are left alone with a warning, since silently rewriting several sections
    would be harder to notice than a duplicate heading.
    """
    header = f"## {heading}"
    new_section = f"{header}\n\n{body.rstrip()}\n"

    lines = text.splitlines(keepends=True)
    header_indices = [i for i, line in enumerate(lines) if line.strip() == header]

    if not header_indices:
        return text.rstrip("\n") + "\n\n" + new_section

    if len(header_indices) > 1:
        sys.stderr.write(
            f"warning: supplied brief.md has {len(header_indices)} `{header}` headers; "
            "replacing the first and leaving the rest unchanged.\n"
        )

    start = header_indices[0]
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    trailer = "\n" if end < len(lines) else ""
    return "".join([*lines[:start], new_section, trailer, *lines[end:]])
