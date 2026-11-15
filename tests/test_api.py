"""Consumer repos import only from `fact_finder.api`, so a name leaves it only on purpose."""

from __future__ import annotations

from fact_finder import api

PUBLIC_NAMES = {
    "ReadOnlySql",
    "enabled_bundles",
    "first_unsafe_line",
    "load_bundle",
    "problem",
    "run_doctor",
    "setup_repo",
    "sql_backed_families",
}


def test_api_exports_exactly_the_public_names() -> None:
    assert set(api.__all__) == PUBLIC_NAMES, (
        "src/fact_finder/api.py: __all__ changed. Fix: update PUBLIC_NAMES in tests/test_api.py, "
        "and repin every consumer that imports a removed name"
    )
    missing = [name for name in api.__all__ if not hasattr(api, name)]
    assert not missing, f"src/fact_finder/api.py: {missing} are not defined. Fix: import them"
