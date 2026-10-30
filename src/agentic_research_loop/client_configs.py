"""Generate each client's MCP config and write-tool deny list from one definition.

Claude Code reads `.mcp.json` and `.claude/settings.json`. Cursor reads
`.cursor/mcp.json` and `.cursor/cli.json`. Codex reads `.codex/config.toml`.

These files belong to the user. The engine adds only what is missing and records what
it added in `Wiring`, so it never overwrites a user's value and removes only its own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

import tomlkit
from pydantic import JsonValue, TypeAdapter, ValidationError
from tomlkit.exceptions import TOMLKitError
from tomlkit.toml_document import TOMLDocument

from .io import read_text
from .layout import as_table
from .sources import Client, ServerDefinition, SourceConfigError, Wiring

JsonObject = dict[str, JsonValue]
JSON_OBJECT = TypeAdapter(JsonObject)

CLAUDE_MCP = ".mcp.json"
CURSOR_MCP = ".cursor/mcp.json"
CODEX_CONFIG = ".codex/config.toml"
CLAUDE_SETTINGS = ".claude/settings.json"
CURSOR_PERMISSIONS = ".cursor/cli.json"
CLIENTS: tuple[Client, ...] = get_args(Client)
CLIENT_FILES: dict[Client, str] = {
    "claude": CLAUDE_MCP,
    "cursor": CURSOR_MCP,
    "codex": CODEX_CONFIG,
}
GoalsState = Literal["enabled", "disabled", "unset"]


def claude_server(server: ServerDefinition) -> JsonObject:
    if server.url is None:
        return {"type": "stdio", "command": server.command, "args": list(server.args)}
    shape: JsonObject = {"type": "http", "url": server.url}
    if server.oauth is not None:
        shape["oauth"] = {
            "clientId": server.oauth.client_id,
            "callbackPort": server.oauth.callback_port,
        }
    return shape


def cursor_server(server: ServerDefinition) -> JsonObject:
    if server.url is None:
        return {"type": "stdio", "command": server.command, "args": list(server.args)}
    return {"url": server.url}


def codex_server(server: ServerDefinition) -> JsonObject:
    shape: JsonObject = (
        {"url": server.url}
        if server.url is not None
        else {"command": server.command, "args": list(server.args)}
    )
    shape["enabled"] = True
    if server.write_tools:
        shape["disabled_tools"] = list(server.write_tools)
    return shape


def claude_deny_rules(server: ServerDefinition) -> list[str]:
    return [f"mcp__{server.server_name}__{tool}" for tool in server.write_tools]


def cursor_deny_rules(server: ServerDefinition) -> list[str]:
    return [f"Mcp({server.server_name}:{tool})" for tool in server.write_tools]


def _read_json_object(path: Path) -> JsonObject:
    if not path.exists():
        return {}
    try:
        return JSON_OBJECT.validate_json(read_text(path))
    except ValidationError as exc:
        raise SourceConfigError(
            f"{path} is not a JSON object: {exc.errors()[0]['msg']}"
        ) from exc


def _read_toml(path: Path) -> TOMLDocument:
    if not path.exists():
        return tomlkit.document()
    try:
        return tomlkit.parse(read_text(path))
    except TOMLKitError as exc:
        raise SourceConfigError(f"{path} is not valid TOML: {exc}") from exc


def _child_object(parent: JsonObject, key: str) -> JsonObject:
    child = parent.get(key)
    if isinstance(child, dict):
        return child
    created: JsonObject = {}
    parent[key] = created
    return created


def deny_rules(document: JsonObject) -> list[str]:
    permissions = document.get("permissions")
    deny = permissions.get("deny") if isinstance(permissions, dict) else None
    return (
        [rule for rule in deny if isinstance(rule, str)]
        if isinstance(deny, list)
        else []
    )


def _add_deny_rules(document: JsonObject, rules: list[str]) -> list[str]:
    """Add the missing rules and return only those, so that disable removes only them."""
    existing = deny_rules(document)
    added = [rule for rule in rules if rule not in existing]
    if added:
        permissions = _child_object(document, "permissions")
        deny = permissions.get("deny")
        permissions["deny"] = [*(deny if isinstance(deny, list) else []), *added]
    return added


def _remove_deny_rules(document: JsonObject, rules: list[str]) -> None:
    permissions = document.get("permissions")
    if not isinstance(permissions, dict):
        return
    deny = permissions.get("deny")
    if isinstance(deny, list):
        permissions["deny"] = [rule for rule in deny if rule not in rules]


def _render(document: JsonObject) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


@dataclass(frozen=True)
class WireResult:
    wiring: Wiring
    added_files: list[str]
    denied: bool


@dataclass
class ClientConfigs:
    """Every client file, parsed in memory. `documents` returns what changed."""

    root: Path
    claude_mcp: JsonObject
    cursor_mcp: JsonObject
    codex: Any
    claude_settings: JsonObject
    cursor_permissions: JsonObject

    @classmethod
    def read(cls, root: Path) -> ClientConfigs:
        return cls(
            root=root,
            claude_mcp=_read_json_object(root / CLAUDE_MCP) or {"mcpServers": {}},
            cursor_mcp=_read_json_object(root / CURSOR_MCP) or {"mcpServers": {}},
            codex=_read_toml(root / CODEX_CONFIG),
            claude_settings=_read_json_object(root / CLAUDE_SETTINGS),
            cursor_permissions=_read_json_object(root / CURSOR_PERMISSIONS),
        )

    def _codex_servers(self) -> Any:
        servers: Any = self.codex.get("mcp_servers")
        if servers is None:
            servers = tomlkit.table(is_super_table=True)
            self.codex["mcp_servers"] = servers
        return servers

    def server_entry(self, client: Client, server_name: str) -> dict[str, Any] | None:
        """Return a client's plain entry for a server, or None when it has none."""
        document: object = {
            "claude": self.claude_mcp,
            "cursor": self.cursor_mcp,
            "codex": self.codex.unwrap(),
        }[client]
        key = "mcp_servers" if client == "codex" else "mcpServers"
        entry = as_table(as_table(as_table(document).get(key)).get(server_name))
        return entry or None

    def _add_server(self, client: Client, server: ServerDefinition) -> None:
        name = server.server_name
        if client == "claude":
            _child_object(self.claude_mcp, "mcpServers")[name] = claude_server(server)
        elif client == "cursor":
            _child_object(self.cursor_mcp, "mcpServers")[name] = cursor_server(server)
        else:
            table = tomlkit.table()
            for key, value in codex_server(server).items():
                table[key] = value
            self._codex_servers()[name] = table

    def _remove_server(self, client: Client, server_name: str) -> None:
        if client == "codex":
            servers: Any = self.codex.get("mcp_servers")
            if servers is not None:
                servers.pop(server_name, None)
                if not servers:
                    self.codex.pop("mcp_servers")
        else:
            document = self.claude_mcp if client == "claude" else self.cursor_mcp
            _child_object(document, "mcpServers").pop(server_name, None)

    def _add_codex_disabled_tools(self, server: ServerDefinition) -> list[str]:
        """Add write tools an engine-owned Codex entry lacks, keeping its other values."""
        table = self._codex_servers()[server.server_name]
        disabled: list[str] = list(table.get("disabled_tools", []))
        added = [tool for tool in server.write_tools if tool not in disabled]
        if added:
            table["disabled_tools"] = [*disabled, *added]
        return added

    def wire(self, server: ServerDefinition, owned: Wiring | None) -> WireResult:
        """Add what is missing, keep every existing value, and say what really changed.

        A server the engine did not add is the user's. That is a collision: raise, so
        the caller writes nothing.
        """
        owned_clients = owned.clients if owned else []
        foreign = [
            CLIENT_FILES[client]
            for client in CLIENTS
            if client not in owned_clients
            and self.server_entry(client, server.server_name)
        ]
        if foreign:
            raise SourceConfigError(
                f"Server '{server.server_name}' already exists in {', '.join(foreign)} and "
                "was not added by research. Nothing changed. Rename or remove that "
                "entry, then run the command again."
            )
        added_clients: list[Client] = [
            client
            for client in CLIENTS
            if not self.server_entry(client, server.server_name)
        ]
        for client in added_clients:
            self._add_server(client, server)
        added_codex = self._add_codex_disabled_tools(server)
        added_claude = _add_deny_rules(self.claude_settings, claude_deny_rules(server))
        added_cursor = _add_deny_rules(
            self.cursor_permissions, cursor_deny_rules(server)
        )
        wiring = Wiring(
            server_name=server.server_name,
            clients=list(CLIENTS),
            claude_deny=list(
                dict.fromkeys([*(owned.claude_deny if owned else []), *added_claude])
            ),
            cursor_deny=list(
                dict.fromkeys([*(owned.cursor_deny if owned else []), *added_cursor])
            ),
        )
        return WireResult(
            wiring=wiring,
            added_files=[CLIENT_FILES[client] for client in added_clients],
            denied=bool(added_claude or added_cursor or added_codex),
        )

    def unwire(self, wiring: Wiring) -> None:
        for client in wiring.clients:
            self._remove_server(client, wiring.server_name)
        _remove_deny_rules(self.claude_settings, wiring.claude_deny)
        _remove_deny_rules(self.cursor_permissions, wiring.cursor_deny)

    def goals_state(self) -> GoalsState:
        value = as_table(as_table(self.codex.unwrap()).get("features")).get("goals")
        if value is None:
            return "unset"
        return "enabled" if value is True else "disabled"

    def enable_codex_goals(self) -> None:
        """Add the goals flag Codex hides `/goal` behind, keeping an explicit choice."""
        if self.goals_state() != "unset":
            return
        features: Any = self.codex.get("features")
        if features is None:
            features = tomlkit.table()
            self.codex["features"] = features
        elif not hasattr(features, "append"):
            raise SourceConfigError(f"{CODEX_CONFIG}: `features` is not a table.")
        features["goals"] = True

    def documents(self) -> dict[Path, str]:
        """Return each client file whose content changed."""
        contents: dict[str, JsonObject | None] = {
            CLAUDE_MCP: self.claude_mcp,
            CURSOR_MCP: self.cursor_mcp,
            CLAUDE_SETTINGS: self.claude_settings or None,
            CURSOR_PERMISSIONS: self.cursor_permissions or None,
        }
        rendered = {
            relative: _render(document)
            for relative, document in contents.items()
            if document is not None
        }
        rendered[CODEX_CONFIG] = tomlkit.dumps(self.codex)
        changed: dict[Path, str] = {}
        for relative, content in rendered.items():
            path = self.root / relative
            if not path.exists() or read_text(path) != content:
                changed[path] = content
        return changed
