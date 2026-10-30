from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    """Replace a file atomically. A symlink keeps pointing at its target."""
    target = path.resolve() if path.is_symlink() else path
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    tmp = Path(name)
    # mkstemp creates 0600. Keep an existing file's mode, else use a normal one.
    tmp.chmod(target.stat().st_mode if target.exists() else 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)


def write_documents(documents: dict[Path, str]) -> None:
    """Write files in order. If one write fails, restore those already written."""
    written: list[tuple[Path, str | None]] = []
    try:
        for path, content in documents.items():
            previous = read_text(path) if path.exists() else None
            write_text(path, content)
            written.append((path, previous))
    except OSError:
        for path, previous in reversed(written):
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                write_text(path, previous)
        raise


def extract_section(
    text: str, heading: str, max_chars: int | None = None
) -> str | None:
    """Extract the body of a ## heading section (case-insensitive).

    Returns None if the section is absent or empty.
    """
    pattern = rf"^## {re.escape(heading)}[ \t]*\n+(.*?)(?=^##\s|\Z)"
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if match is None:
        return None
    body = match.group(1).strip()
    if not body or body == "-":
        return None
    if max_chars is not None and len(body) > max_chars:
        return body[:max_chars] + "..."
    return body
