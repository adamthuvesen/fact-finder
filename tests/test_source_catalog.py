from __future__ import annotations

from pathlib import Path

import pytest

from agentic_research_loop.source_bundles import available_bundles, load_bundle
from agentic_research_loop.source_catalog import (
    expected_documents,
    render_catalog,
    render_summary,
)

ROOT = Path(__file__).resolve().parents[1]


def test_generated_source_lists_have_not_drifted() -> None:
    stale = [
        str(path.relative_to(ROOT))
        for path, expected in expected_documents(ROOT).items()
        if path.read_text(encoding="utf-8") != expected
    ]

    assert stale == [], "Run: uv run python scripts/generate_source_docs.py"


@pytest.mark.parametrize("render", [render_summary, render_catalog])
def test_every_bundle_appears_in_every_list(render) -> None:
    text = render(ROOT)

    for name in available_bundles(ROOT):
        assert load_bundle(ROOT, name).spec.display_name in text, name


def test_a_document_without_markers_is_an_error(tmp_path) -> None:
    (tmp_path / "README.md").write_text("no markers\n", encoding="utf-8")
    (tmp_path / "program.md").write_text("no markers\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing marker block"):
        expected_documents(tmp_path)
