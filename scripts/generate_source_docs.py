#!/usr/bin/env python3
"""Rewrite the generated source lists in the docs from each bundle's source.json.

Run from the repo root: ``uv run python scripts/generate_source_docs.py``
`tests/test_source_catalog.py` fails when a generated list has drifted.
"""

from __future__ import annotations

from pathlib import Path

from agentic_research_loop.source_catalog import expected_documents

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    for path, content in expected_documents(ROOT).items():
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
