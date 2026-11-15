"""No file may turn strict type checking off, ignore a type error without a rule and a reason, or skip a test without a reason."""

import ast
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOWNGRADE = re.compile(
    r"^\s*#\s*pyright:\s*(?:[^#\n]*,\s*)?(?:basic|standard|off|recommended|all|strict\s*=\s*false)\b"
)
UNEXPLAINED_IGNORE = re.compile(r"#\s*pyright:\s*ignore(?!\[[^\]]+\]\s*--\s*\S)")


def is_python_file(path: Path) -> bool:
    if path.suffix:
        return path.suffix == ".py"
    with path.open("rb") as handle:
        first_line = handle.readline()
    return first_line.startswith(b"#!") and b"python" in first_line


def repo_python_files(root: Path) -> list[Path]:
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        env=env,
        capture_output=True,
        check=True,
    ).stdout.decode()
    paths = (root / name for name in listing.split("\0") if name)
    return [path for path in paths if path.is_file() and is_python_file(path)]


def downgrades(root: Path) -> list[str]:
    return [
        f"{path.relative_to(root)}:{number}"
        for path in repo_python_files(root)
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1)
        if DOWNGRADE.match(line) or UNEXPLAINED_IGNORE.search(line)
    ]


def test_no_file_downgrades_type_checking_mode() -> None:
    found = downgrades(ROOT)
    assert not found, (
        "a `# pyright:` comment turns strict mode off, or an ignore names no rule or reason: "
        + ", ".join(found)
        + ". Fix: remove the comment and fix the type error, or write "
        "`# pyright: ignore[<rule>] -- <reason>`"
    )


def test_the_scan_finds_a_downgrade_in_a_new_unstaged_file(tmp_path: Path) -> None:
    """A scan that finds nothing passes, so prove it still finds known cases."""
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, env=env, check=True)
    (tmp_path / "new.py").write_text("# pyright: basic\n")
    (tmp_path / "script").write_text("#!/usr/bin/env python3\n# pyright: strict=false\n")
    (tmp_path / "fine.py").write_text("# pyright: reportAny=false\n")
    hash_mark = "#"
    (tmp_path / "bare.py").write_text(f"x = 1  {hash_mark} pyright: ignore\n")
    (tmp_path / "reasonless.py").write_text(f"x = 1  {hash_mark} pyright: ignore[reportAny]\n")
    (tmp_path / "reasoned.py").write_text("x = 1  # pyright: ignore[reportAny] -- why\n")

    assert sorted(downgrades(tmp_path)) == [
        "bare.py:1",
        "new.py:1",
        "reasonless.py:1",
        "script:2",
    ]


SKIP_MARKS = frozenset({"pytest.mark.skip", "pytest.mark.xfail", "pytest.skip", "unittest.skip"})
KEYWORD_REASON_MARKS = frozenset({"pytest.mark.skip", "pytest.mark.xfail"})


def dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = dotted_name(node.value)
        return None if owner is None else f"{owner}.{node.attr}"
    return None


def has_reason(call: ast.Call, name: str) -> bool:
    reason = next((keyword.value for keyword in call.keywords if keyword.arg == "reason"), None)
    if reason is None and name not in KEYWORD_REASON_MARKS and call.args:
        reason = call.args[0]
    return (
        isinstance(reason, ast.Constant)
        and isinstance(reason.value, str)
        and reason.value.strip() != ""
    )


def skips_without_reason(root: Path) -> list[str]:
    found: list[str] = []
    for path in repo_python_files(root):
        tree = ast.parse(path.read_text(errors="replace"))
        called: set[ast.AST] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = dotted_name(node.func)
            if name in SKIP_MARKS:
                called.add(node.func)
                if not has_reason(node, name):
                    found.append(f"{path.relative_to(root)}:{node.lineno}")
        found.extend(
            f"{path.relative_to(root)}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node not in called
            and dotted_name(node) in SKIP_MARKS
        )
    return found


def test_every_skip_has_a_reason() -> None:
    found = skips_without_reason(ROOT)
    assert not found, (
        "a skip or xfail has no reason string: "
        + ", ".join(found)
        + '. Fix: pass a literal reason, for example `pytest.mark.skip(reason="needs the network")`'
    )


def test_the_skip_scan_finds_a_skip_without_a_reason(tmp_path: Path) -> None:
    """A scan that finds nothing passes, so prove it still finds known cases."""
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, env=env, check=True)
    (tmp_path / "bare.py").write_text(
        "import pytest\n\n@pytest.mark.skip\ndef test_a() -> None: ...\n"
    )
    (tmp_path / "empty.py").write_text(
        'import pytest\n\n@pytest.mark.xfail(reason="")\ndef test_b() -> None: ...\n'
    )
    (tmp_path / "bare_call.py").write_text("import pytest\n\npytest.skip()\n")
    (tmp_path / "unittest_bare.py").write_text(
        "import unittest\n\n@unittest.skip\ndef test_c(): ...\n"
    )
    (tmp_path / "fine.py").write_text(
        "import pytest\nimport unittest\n\n"
        '@pytest.mark.skip(reason="needs the network")\n'
        "def test_d() -> None: ...\n"
        'pytest.skip("needs a GPU")\n'
        '@unittest.skip("unused")\n'
        "def test_e(): ...\n"
    )

    assert sorted(skips_without_reason(tmp_path)) == [
        "bare.py:3",
        "bare_call.py:3",
        "empty.py:3",
        "unittest_bare.py:3",
    ]
