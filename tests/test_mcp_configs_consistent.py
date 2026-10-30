"""This repo ships neutral client configs, so a clone carries nobody's stack.

`research source enable` generates all client shapes from one definition, so they
cannot drift. `research doctor` catches a hand edit. This test catches an enabled
config committed back.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_committed_mcp_configs_ship_neutral() -> None:
    assert json.loads((ROOT / ".mcp.json").read_text())["mcpServers"] == {}
    codex = ROOT / ".codex" / "config.toml"
    if codex.exists():
        assert tomllib.loads(codex.read_text()).get("mcp_servers", {}) == {}
    cursor = ROOT / ".cursor" / "mcp.json"
    if cursor.exists():
        assert json.loads(cursor.read_text())["mcpServers"] == {}
