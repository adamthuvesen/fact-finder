#!/usr/bin/env python3
"""Check the local prerequisites for running research inside a native goal.

The MCP server list is read from the local `.mcp.json`, so this checks
exactly the bundles you enabled rather than a fixed roster. `.codex/config.toml`
and `.cursor/mcp.json` are local-only files created by `research source enable`.
`research doctor` checks that the three agree and that read-only controls hold.

Run from the repo root: ``uv run python scripts/check_agent_setup.py``
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MCP = ROOT / ".mcp.json"
CODEX_CONFIG = ROOT / ".codex" / "config.toml"


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    message: str


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)


def _load_servers() -> dict[str, dict[str, Any]]:
    if not CLAUDE_MCP.exists():
        return {}
    payload = json.loads(CLAUDE_MCP.read_text(encoding="utf-8"))
    servers = payload.get("mcpServers", {})
    return servers if isinstance(servers, dict) else {}


def _check_command(name: str) -> CheckResult:
    if shutil.which(name):
        return CheckResult(name, ok=True, message="installed")
    return CheckResult(name, ok=False, message="missing from PATH")


def _check_claude_goals() -> CheckResult:
    """Claude Code has no feature probe for goals, so check for a recent CLI."""
    if not shutil.which("claude"):
        return CheckResult("claude-goals", ok=False, message="skipped because claude is missing")
    result = _run(["claude", "--version"])
    if result.returncode != 0:
        return CheckResult(
            "claude-goals", ok=False, message="could not read the Claude Code version"
        )
    version = result.stdout.strip() or "unknown version"
    return CheckResult(
        "claude-goals",
        ok=True,
        message=f"{version} — run `/goal` in Claude Code to confirm it is available",
    )


def _check_codex_goals() -> CheckResult:
    """Codex gates goals behind a feature flag, which `codex features` reports."""
    if not shutil.which("codex"):
        return CheckResult(
            "codex-goals", ok=True, message="optional — codex is not on PATH, skipping"
        )
    result = _run(["codex", "features", "list"])
    enabled = any(
        line.split()[:3] == ["goals", "stable", "true"] for line in result.stdout.splitlines()
    )
    if result.returncode == 0 and enabled:
        return CheckResult("codex-goals", ok=True, message="stable feature enabled")
    return CheckResult(
        "codex-goals",
        ok=False,
        message=f"not enabled. Add `[features] goals = true` to {CODEX_CONFIG.name}",
    )


def _check_server(name: str, spec: dict[str, Any]) -> CheckResult:
    result = _run(["claude", "mcp", "get", name])
    if result.returncode == 0:
        return CheckResult(name, ok=True, message="reachable from Claude")

    output = "\n".join(
        part for part in (result.stdout.strip(), result.stderr.strip()) if part
    ).strip()
    hint = output or "health check failed"
    if "url" in spec:
        # Remote servers authenticate per provider on first use.
        hint += " | First run: use `/mcp` in Claude Code to approve and authenticate."
    else:
        hint += " | Run `research source show <name>` for its credential or config step."
    return CheckResult(name, ok=False, message=hint)


def _server_checks(servers: dict[str, dict[str, Any]]) -> list[CheckResult]:
    if not servers:
        return [
            CheckResult(
                "mcp-servers",
                ok=True,
                message="none wired — fine for web-search and --context-path cases. "
                "Add one with `research source enable <name>`",
            )
        ]
    if not shutil.which("claude"):
        return [
            CheckResult(name, ok=False, message="skipped — claude command is missing")
            for name in servers
        ]
    return [_check_server(name, spec) for name, spec in servers.items()]


def main() -> int:
    servers = _load_servers()
    checks = [
        _check_command("uv"),
        _check_command("claude"),
        _check_claude_goals(),
        _check_codex_goals(),
        *_server_checks(servers),
    ]

    sys.stdout.write("Native goal research setup\n")
    sys.stdout.write(f"Repo: {ROOT}\n\n")

    for check in checks:
        sys.stdout.write(f"[{'PASS' if check.ok else 'FAIL'}] {check.name}: {check.message}\n")

    if all(check.ok for check in checks):
        sys.stdout.write("\nReady to run a case inside a native goal.\n")
        return 0

    sys.stdout.write("\nSee `.agents/docs/setup.md` for authentication and setup steps.\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
