"""`research doctor`: check enabled servers against their declared read-only control.

This reads local config files. It does not contact any server. A passing doctor says
the config matches the declaration, and says nothing about what the upstream server
actually does. It compares each client's wired entry with the bundle definition. A value
the definition declares as user-filled is fine, and any other target or argument is not.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import TypeAdapter, ValidationError

from .client_configs import (
    CLAUDE_SETTINGS,
    CLIENT_FILES,
    CLIENTS,
    CODEX_CONFIG,
    CURSOR_PERMISSIONS,
    ClientConfigs,
    claude_deny_rules,
    cursor_deny_rules,
    deny_rules,
)
from .io import read_text
from .layout import as_table
from .source_bundles import Bundle, enabled_bundles
from .sources import (
    CONFIG_CHECKED,
    ReadOnlyControl,
    ServerDefinition,
    SourceConfigError,
)

READ_ONLY_STATEMENTS = frozenset({"Select", "Describe", "Show", "Use"})
PERMISSIONS = TypeAdapter(list[dict[str, bool]])
Status = Literal["pass", "fail", "declared", "needs-setup"]


@dataclass(frozen=True)
class DoctorCheck:
    source: str
    status: Status
    message: str


def _permissions_problem(value: object) -> str | None:
    try:
        permissions = PERMISSIONS.validate_python(value, strict=True)
    except ValidationError:
        return "needs sql_statement_permissions as a list of `Verb: true|false` entries"
    allowed = {verb for entry in permissions for verb, flag in entry.items() if flag}
    if not allowed:
        return "allows no statement"
    extra = allowed - READ_ONLY_STATEMENTS
    return f"allows {', '.join(sorted(extra))}" if extra else None


def allowlist_problem(text: str) -> str | None:
    """Return why a Snowflake tools file is not read-only, or None if it is."""
    try:
        settings = as_table(yaml.safe_load(text))
    except yaml.YAMLError as exc:
        return f"is not valid YAML: {exc}"
    problem = _permissions_problem(settings.get("sql_statement_permissions"))
    if problem is None and as_table(settings.get("other_services")).get(
        "semantic_manager"
    ):
        return "enables semantic_manager, whose write tool bypasses the allowlist"
    return problem


def control_problem(
    repo_root: Path, control: ReadOnlyControl, *, url: str, args: list[str]
) -> str | None:
    """Return why a server breaks its declared control, or None if it holds."""
    match control.mechanism:
        case "url_suffix" if not (
            url.endswith(control.detail) or f"{control.detail}/" in url
        ):
            return f"url does not end with {control.detail}"
        case "server_flag" if control.detail not in args:
            return f"args do not include {control.detail}"
        case "arg_absent" if control.detail in args:
            return f"args include {control.detail}"
        case "statement_allowlist":
            return _statement_allowlist_problem(repo_root, control.detail, args)
        case _:
            return None


def _statement_allowlist_problem(
    repo_root: Path, relative: str, args: list[str]
) -> str | None:
    if relative not in args:
        return f"args do not pass {relative}"
    path = repo_root / relative
    if not path.exists():
        return f"{relative} is missing"
    problem = allowlist_problem(read_text(path))
    return f"{relative} {problem}" if problem else None


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
    `headers`, hold the credentials SETUP.md tells the user to add.
    """
    differences = [
        f"{key} is {entry.get(key)!r}"
        for key, default in (("url", server.url), ("command", server.command))
        if not _matches(entry.get(key), default, server)
    ]
    args = _without_optional_args([str(arg) for arg in entry.get("args", [])], server)
    if len(args) != len(server.args) or not all(
        _matches(arg, default, server)
        for arg, default in zip(args, server.args, strict=True)
    ):
        differences.append(f"args are {args!r}")
    return differences


def _client_checks(
    repo_root: Path, clients: ClientConfigs, bundle: Bundle, server: ServerDefinition
) -> list[DoctorCheck]:
    control = bundle.spec.read_only_control
    setup = bundle.path / "SETUP.md"
    checks: list[DoctorCheck] = []
    for client in CLIENTS:
        label = CLIENT_FILES[client]
        entry = clients.server_entry(client, server.server_name)
        if entry is None:
            checks.append(DoctorCheck(bundle.name, "fail", f"not wired in {label}"))
            continue
        checks.extend(
            DoctorCheck(
                bundle.name,
                "needs-setup",
                f"replace {placeholder} in {label}; see {setup}",
            )
            for placeholder in server.placeholders
            if placeholder in json.dumps(entry)
        )
        checks.extend(
            DoctorCheck(
                bundle.name, "fail", f"{label} differs from the bundle: {difference}"
            )
            for difference in server_differences(entry, server)
        )
        if control.mechanism in CONFIG_CHECKED:
            problem = control_problem(
                repo_root,
                control,
                url=str(entry.get("url", "")),
                args=[str(arg) for arg in entry.get("args", [])],
            )
            if problem:
                checks.append(
                    DoctorCheck(
                        bundle.name, "fail", f"{label}: {control.mechanism}: {problem}"
                    )
                )
    return checks


def _deny_checks(
    clients: ClientConfigs, bundle: Bundle, server: ServerDefinition
) -> list[DoctorCheck]:
    missing: list[tuple[str, str]] = []
    claude = deny_rules(clients.claude_settings)
    cursor = deny_rules(clients.cursor_permissions)
    missing += [
        (CLAUDE_SETTINGS, r) for r in claude_deny_rules(server) if r not in claude
    ]
    missing += [
        (CURSOR_PERMISSIONS, r) for r in cursor_deny_rules(server) if r not in cursor
    ]
    entry = clients.server_entry("codex", server.server_name)
    if entry is not None:
        disabled: list[str] = entry.get("disabled_tools", [])
        missing += [(CODEX_CONFIG, t) for t in server.write_tools if t not in disabled]
    return [
        DoctorCheck(
            bundle.name,
            "fail",
            f"{label} does not deny {rule}. Run `research setup` to restore it.",
        )
        for label, rule in missing
    ]


def _check_bundle(
    repo_root: Path, clients: ClientConfigs, bundle: Bundle
) -> list[DoctorCheck]:
    control = bundle.spec.read_only_control
    checks: list[DoctorCheck] = []
    if bundle.server is not None:
        checks += _client_checks(repo_root, clients, bundle, bundle.server)
        checks += _deny_checks(clients, bundle, bundle.server)
    if control.mechanism not in CONFIG_CHECKED:
        checks.append(
            DoctorCheck(
                bundle.name,
                "declared",
                f"{control.mechanism}: {control.detail}. Config cannot prove this; "
                f"follow {bundle.path / 'SETUP.md'}.",
            )
        )
    elif not checks:
        checks.append(
            DoctorCheck(bundle.name, "pass", f"{control.mechanism}: {control.detail}")
        )
    return checks


def _goals_checks(repo_root: Path, clients: ClientConfigs) -> list[DoctorCheck]:
    if not (repo_root / CODEX_CONFIG).exists():
        return []
    state = clients.goals_state()
    if state == "enabled":
        return []
    return [
        DoctorCheck(
            CODEX_CONFIG,
            "fail",
            f"native goals are {state}. Set `goals = true` under `[features]`.",
        )
    ]


def run_doctor(repo_root: Path) -> list[DoctorCheck]:
    bundles, without_bundle = enabled_bundles(repo_root)
    try:
        clients = ClientConfigs.read(repo_root)
    except SourceConfigError as exc:
        return [DoctorCheck("client config", "fail", str(exc))]
    checks = _goals_checks(repo_root, clients)
    checks.extend(
        check
        for bundle in bundles
        for check in _check_bundle(repo_root, clients, bundle)
    )
    checks.extend(
        DoctorCheck(name, "declared", "no bundle, so nothing can be checked")
        for name in without_bundle
    )
    return checks
