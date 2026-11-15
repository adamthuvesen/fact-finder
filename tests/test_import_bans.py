"""A per-file ignore turns the TID251 import bans off for a whole file, so only named owners get one."""

import tomllib
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
BAN_OWNERS = frozenset(
    {
        ".agents/skills/*/verify",
        "scripts/check_agent_setup.py",
        "src/fact_finder/strict_model.py",
        "tests/**",
    }
)
REQUIRED_BANS = frozenset(
    {"anthropic", "openai", "claude_agent_sdk", "subprocess", "os.system", "asyncio", "pty"}
)


def _ruff_lint() -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["ruff"]["lint"],
    )


def test_only_named_owners_skip_the_import_bans() -> None:
    ignores = cast("dict[str, list[str]]", _ruff_lint()["per-file-ignores"])
    skipping = {path for path, rules in ignores.items() if any(r.startswith("TID") for r in rules)}
    assert skipping <= BAN_OWNERS, (
        f"pyproject.toml [tool.ruff.lint.per-file-ignores]: these files skip the TID251 bans: "
        f"{sorted(skipping - BAN_OWNERS)}. Only BAN_OWNERS in tests/test_import_bans.py may. "
        "Fix: remove the TID entry and remove the banned import instead."
    )


def test_the_core_bans_stay_listed() -> None:
    banned = set(cast("dict[str, object]", _ruff_lint()["flake8-tidy-imports"]["banned-api"]))
    assert banned >= REQUIRED_BANS, (
        f"pyproject.toml [tool.ruff.lint.flake8-tidy-imports.banned-api]: core bans removed: "
        f"{sorted(REQUIRED_BANS - banned)}. Fix: restore each ban with its msg."
    )
