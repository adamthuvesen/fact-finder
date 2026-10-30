"""Generate each client's MCP config and write-tool deny list from one definition.

Claude Code reads `.mcp.json`, and merges the deny lists of `.claude/settings.json` and the
untracked `.claude/settings.local.json`. A source's rules go in the local file, so enabling one
leaves shared settings alone. Connector rules go in the shared file, because every clone can reach
a claude.ai connector. Cursor reads
`.cursor/mcp.json` and `.cursor/cli.json`. Codex reads `.codex/config.toml`.

These files belong to the user. The engine records what it added in `Wiring`. An entry it does
not own is never changed. In an entry it owns, it keeps every value a person may set, and brings
what chooses the server back to the bundle.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast, get_args

import tomlkit
from pydantic import JsonValue, TypeAdapter, ValidationError
from tomlkit.exceptions import TOMLKitError
from tomlkit.toml_document import TOMLDocument

from .feedback import problem
from .io import read_text
from .layout import as_table
from .sources import Client, ServerDefinition, SourceConfigError, Wiring

JsonObject = dict[str, JsonValue]
JSON_OBJECT = TypeAdapter(JsonObject)

CLAUDE_MCP = ".mcp.json"
CURSOR_MCP = ".cursor/mcp.json"
CODEX_CONFIG = ".codex/config.toml"
CLAUDE_SETTINGS = ".claude/settings.json"
CLAUDE_LOCAL_SETTINGS = ".claude/settings.local.json"
CURSOR_PERMISSIONS = ".cursor/cli.json"
CLIENTS: tuple[Client, ...] = get_args(Client)
CLIENT_FILES: dict[Client, str] = {
    "claude": CLAUDE_MCP,
    "cursor": CURSOR_MCP,
    "codex": CODEX_CONFIG,
}
GoalsState = Literal["enabled", "disabled", "unset"]


SERVER_CHOICE_KEYS = ("type", "url", "command", "args")


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


def _value_pattern(value: str, server: ServerDefinition) -> str:
    pattern = re.escape(value).replace(re.escape("@latest"), r"@[\w.-]+")
    for placeholder in server.placeholders:
        fill = r"/\S+" if placeholder.startswith("/") else r"[^/\s]+"
        pattern = pattern.replace(re.escape(placeholder), fill)
    return "|".join([pattern, *server.alternatives.get(value, [])])


def _matches(value: object, default: str | None, server: ServerDefinition) -> bool:
    if default is None:
        return value is None
    return isinstance(value, str) and bool(
        re.fullmatch(_value_pattern(default, server), value)
    )


def _without_optional_args(args: list[str], server: ServerDefinition) -> list[str]:
    kept: list[str] = []
    skip_value = False
    for arg in args:
        if skip_value:
            skip_value = False
        elif arg in server.optional_args:
            skip_value = True
        elif not any(arg.startswith(f"{flag}=") for flag in server.optional_args):
            kept.append(arg)
    return kept


def server_differences(entry: dict[str, Any], server: ServerDefinition) -> list[str]:
    """Compare what a client would connect to with the bundle's definition.

    Only the url, command, and args choose the server. Other keys, such as `env` and
    `headers`, hold the credentials the bundle's `setup` tells the user to add.
    """
    differences = [
        f"{key} is {entry.get(key)!r}"
        for key, default in (("url", server.url), ("command", server.command))
        if not _matches(entry.get(key), default, server)
    ]
    args = _without_optional_args(entry.get("args", []), server)
    if len(args) != len(server.args) or not all(
        _matches(arg, default, server)
        for arg, default in zip(args, server.args, strict=True)
    ):
        differences.append(f"args are {args!r}")
    return differences


def _disables_write_tools(entry: dict[str, Any], server: ServerDefinition) -> bool:
    return set(server.write_tools) <= set(entry.get("disabled_tools", []))


def read_json_object(path: Path) -> JsonObject:
    if not path.exists():
        return {}
    try:
        return JSON_OBJECT.validate_json(read_text(path))
    except ValidationError as exc:
        raise SourceConfigError(
            problem(
                f"not a JSON object: {exc.errors()[0]['msg']}",
                "correct the syntax",
                file=str(path),
            )
        ) from exc


def _read_toml(path: Path) -> TOMLDocument:
    if not path.exists():
        return tomlkit.document()
    try:
        return tomlkit.parse(read_text(path))
    except TOMLKitError as exc:
        raise SourceConfigError(
            problem(f"not valid TOML: {exc}", "correct the syntax", file=str(path))
        ) from exc


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
    """Remove the rules, and any `deny` or `permissions` block that leaves empty."""
    permissions = document.get("permissions")
    if not isinstance(permissions, dict):
        return
    deny = permissions.get("deny")
    if isinstance(deny, list):
        kept = [rule for rule in deny if rule not in rules]
        if kept:
            permissions["deny"] = kept
        else:
            del permissions["deny"]
    if not permissions:
        del document["permissions"]


def _render(document: JsonObject) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


@dataclass(frozen=True)
class WireResult:
    wiring: Wiring
    added_files: list[str]
    updated_files: list[str]
    conflict_files: list[str]
    denied: bool


@dataclass
class ClientConfigs:
    """Every client file, parsed in memory. `documents` returns what changed."""

    root: Path
    claude_mcp: JsonObject
    cursor_mcp: JsonObject
    codex: Any
    claude_local_settings: JsonObject
    claude_settings: JsonObject
    cursor_permissions: JsonObject
    claude_settings_changed: bool = False

    @classmethod
    def read(cls, root: Path) -> ClientConfigs:
        configs = cls(
            root=root,
            claude_mcp=read_json_object(root / CLAUDE_MCP) or {"mcpServers": {}},
            cursor_mcp=read_json_object(root / CURSOR_MCP) or {"mcpServers": {}},
            codex=_read_toml(root / CODEX_CONFIG),
            claude_local_settings=read_json_object(root / CLAUDE_LOCAL_SETTINGS),
            claude_settings=read_json_object(root / CLAUDE_SETTINGS),
            cursor_permissions=read_json_object(root / CURSOR_PERMISSIONS),
        )
        configs._validate_servers()
        return configs

    def _validate_servers(self) -> None:
        documents = {
            "claude": self.claude_mcp,
            "cursor": self.cursor_mcp,
            "codex": self.codex.unwrap(),
        }
        for client in CLIENTS:
            path = str(self.root / CLIENT_FILES[client])
            key = "mcp_servers" if client == "codex" else "mcpServers"
            servers = documents[client].get(key, {})
            if not isinstance(servers, dict):
                raise SourceConfigError(
                    problem(
                        f"{key} must be an object",
                        f"write {key} as an object",
                        file=path,
                    )
                )
            for name, entry in cast("dict[str, object]", servers).items():
                if not isinstance(entry, dict):
                    raise SourceConfigError(
                        problem(
                            f"server '{name}' must be an object",
                            f"write {key}.{name} as an object",
                            file=path,
                        )
                    )
                entry_fields = cast("dict[str, object]", entry)
                fields = {
                    "url": TypeAdapter(str),
                    "command": TypeAdapter(str),
                    "args": TypeAdapter(list[str]),
                }
                if client == "codex":
                    fields["disabled_tools"] = TypeAdapter(list[str])
                for field, adapter in fields.items():
                    if field not in entry_fields:
                        continue
                    try:
                        adapter.validate_python(entry_fields[field], strict=True)
                    except ValidationError as exc:
                        error = exc.errors()[0]
                        location = field + "".join(f"[{part}]" for part in error["loc"])
                        shape = (
                            "a list of strings"
                            if error["type"] == "list_type"
                            else "a string"
                        )
                        raise SourceConfigError(
                            problem(
                                f"server '{name}' field {location} must be {shape}",
                                f"write {key}.{name}.{location} as {shape}",
                                file=path,
                            )
                        ) from exc

    @property
    def claude_shared_deny(self) -> list[str]:
        return deny_rules(self.claude_settings)

    def deny_in_shared_settings(self, rules: list[str]) -> list[str]:
        """Add connector rules to the shared file, and return the ones it lacked.

        A rule is never removed: an extra deny fails closed, and other clones share the file.
        """
        added = _add_deny_rules(self.claude_settings, rules)
        self.claude_settings_changed |= bool(added)
        return added

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

    def _retarget(self, client: Client, server: ServerDefinition) -> None:
        """Point an owned entry at the bundle's server, keeping every other key."""
        name = server.server_name
        if client == "codex":
            entry: Any = self._codex_servers()[name]
            shape = codex_server(server)
        elif client == "claude":
            entry = _child_object(self.claude_mcp, "mcpServers")[name]
            shape = claude_server(server)
        else:
            entry = _child_object(self.cursor_mcp, "mcpServers")[name]
            shape = cursor_server(server)
        for key in SERVER_CHOICE_KEYS:
            if key in shape:
                entry[key] = shape[key]
            else:
                entry.pop(key, None)

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

    def conflicts(self, server: ServerDefinition, owned: list[Client]) -> list[Client]:
        """Return each client with an entry research did not add that breaks the bundle."""
        return [
            client
            for client in CLIENTS
            if client not in owned
            and (entry := self.server_entry(client, server.server_name))
            and (
                server_differences(entry, server)
                or (client == "codex" and not _disables_write_tools(entry, server))
            )
        ]

    def wire(self, server: ServerDefinition, owned: Wiring | None) -> WireResult:
        """Bring a server in line with its bundle, and say what really changed.

        In an owned entry, only what chooses the server changes, and only when the bundle does
        not allow its current value. Credentials and other keys stay. An entry research did not
        add is never changed or recorded as owned, so disable cannot remove it. If it already
        does what the bundle asks, it counts as satisfied, as in a committed client file.
        If it does not, it is a conflict for that client alone.
        """
        owned_clients = owned.clients if owned else []
        conflicts = self.conflicts(server, owned_clients)
        added_clients: list[Client] = [
            client
            for client in CLIENTS
            if not self.server_entry(client, server.server_name)
        ]
        for client in added_clients:
            self._add_server(client, server)
        managed: list[Client] = [
            client
            for client in CLIENTS
            if client in owned_clients or client in added_clients
        ]
        updated_clients: list[Client] = [
            client
            for client in managed
            if server_differences(
                self.server_entry(client, server.server_name) or {}, server
            )
        ]
        for client in updated_clients:
            self._retarget(client, server)
        added_codex = (
            self._add_codex_disabled_tools(server) if "codex" in managed else []
        )
        added_claude = (
            []
            if "claude" in conflicts
            else _add_deny_rules(
                self.claude_local_settings,
                [
                    rule
                    for rule in claude_deny_rules(server)
                    if rule not in self.claude_shared_deny
                ],
            )
        )
        added_cursor = (
            []
            if "cursor" in conflicts
            else _add_deny_rules(self.cursor_permissions, cursor_deny_rules(server))
        )
        wiring = Wiring(
            server_name=server.server_name,
            clients=managed,
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
            updated_files=[CLIENT_FILES[client] for client in updated_clients],
            denied=bool(added_claude or added_cursor or added_codex),
            conflict_files=[CLIENT_FILES[client] for client in conflicts],
        )

    def unwire(self, wiring: Wiring) -> None:
        """Remove what research added. A rule stays while its client still has the server."""
        for client in wiring.clients:
            self._remove_server(client, wiring.server_name)
        if not self.server_entry("claude", wiring.server_name):
            _remove_deny_rules(self.claude_local_settings, wiring.claude_deny)
        if not self.server_entry("cursor", wiring.server_name):
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
            raise SourceConfigError(
                problem(
                    "`features` is not a table",
                    "write it as a `[features]` table",
                    file=CODEX_CONFIG,
                )
            )
        features["goals"] = True

    def documents(self) -> dict[Path, str]:
        """Return each client file whose content changed."""
        contents: dict[str, JsonObject] = {
            CLAUDE_MCP: self.claude_mcp,
            CURSOR_MCP: self.cursor_mcp,
            CLAUDE_LOCAL_SETTINGS: self.claude_local_settings,
            CURSOR_PERMISSIONS: self.cursor_permissions,
        }
        rendered = {
            relative: _render(document)
            for relative, document in contents.items()
            if document or (self.root / relative).exists()
        }
        rendered[CODEX_CONFIG] = tomlkit.dumps(self.codex)
        if self.claude_settings_changed:
            # Rendered only on a real change, so a person's own formatting stays.
            rendered[CLAUDE_SETTINGS] = _render(self.claude_settings)
        changed: dict[Path, str] = {}
        for relative, content in rendered.items():
            path = self.root / relative
            if not path.exists() or read_text(path) != content:
                changed[path] = content
        return changed
