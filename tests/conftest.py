from __future__ import annotations

from pathlib import Path

import pytest

# A skipped or expected-to-fail test proves nothing, and pytest exits 0 on one.
UNPROVEN: list[str] = []


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "fact-finder"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'fact-finder'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )
    return root


def pytest_collectreport(report: pytest.CollectReport) -> None:
    if report.skipped:
        UNPROVEN.append(f"{report.nodeid} (skipped)")


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if hasattr(report, "wasxfail"):
        UNPROVEN.append(f"{report.nodeid} ({'xpassed' if report.passed else 'xfailed'})")
    elif report.skipped:
        UNPROVEN.append(f"{report.nodeid} (skipped)")


def pytest_sessionfinish(session: pytest.Session) -> None:
    if UNPROVEN and session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    for test in UNPROVEN:
        terminalreporter.write_line(
            f"{test}: a test that does not run proves nothing. Make it pass or remove it.",
            red=True,
        )
