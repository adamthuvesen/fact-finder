"""`research doctor`: check enabled servers against their declared read-only control.

This reads local config files. It does not contact any server. A passing doctor says
the config matches the declaration, and says nothing about what the upstream server
actually does. It compares each client's wired entry with the bundle definition. A value
the definition declares as user-filled is fine, and any other target or argument is not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import TypeAdapter, ValidationError

from .client_configs import (
    CLAUDE_LOCAL_SETTINGS,
    CLAUDE_SETTINGS,
    CLIENT_FILES,
    CLIENTS,
    CODEX_CONFIG,
    CURSOR_PERMISSIONS,
    ClientConfigs,
    claude_deny_rules,
    cursor_deny_rules,
    deny_rules,
    server_differences,
)
from .feedback import problem
from .io import read_text
from .layout import as_table
from .source_bundles import (
    WIRING_FILE,
    Bundle,
    conflict_problem,
    connector_deny_rules,
    enabled_bundles,
    owned_wiring,
    wiring_is_unwanted,
)
from .sources import (
    CONFIG_CHECKED,
    Client,
    ReadOnlyControl,
    ServerDefinition,
    SourceConfigError,
    Wiring,
    load_sources_file,
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
    reason = _permissions_problem(settings.get("sql_statement_permissions"))
    if reason is None and as_table(settings.get("other_services")).get(
        "semantic_manager"
    ):
        return "enables semantic_manager, whose write tool bypasses the allowlist"
    return reason


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
    reason = allowlist_problem(read_text(path))
    return f"{relative} {reason}" if reason else None


def _client_checks(
    repo_root: Path,
    clients: ClientConfigs,
    bundle: Bundle,
    server: ServerDefinition,
    owned: list[Client],
) -> list[DoctorCheck]:
    control = bundle.spec.read_only_control
    show = f"run `research source show {bundle.name}`"
    restore = "run `research setup`"
    checks: list[DoctorCheck] = []
    conflicts = clients.conflicts(server, owned)
    for client in CLIENTS:
        label = CLIENT_FILES[client]
        entry = clients.server_entry(client, server.server_name)
        if entry is None:
            checks.append(
                DoctorCheck(
                    bundle.name,
                    "fail",
                    problem(
                        f"{bundle.name} is not wired",
                        "run `research setup`",
                        file=label,
                    ),
                )
            )
            continue
        if client in conflicts:
            checks.append(
                DoctorCheck(
                    bundle.name,
                    "fail",
                    conflict_problem(server.server_name, bundle.name, label),
                )
            )
            continue
        checks.extend(
            DoctorCheck(
                bundle.name,
                "needs-setup",
                problem(
                    f"{bundle.name} still has {placeholder}",
                    f"replace it with your value; {show}",
                    file=label,
                ),
            )
            for placeholder in server.placeholders
            if placeholder in json.dumps(entry)
        )
        checks.extend(
            DoctorCheck(
                bundle.name,
                "fail",
                problem(
                    f"{bundle.name} differs from its bundle: {difference}",
                    restore,
                    file=label,
                ),
            )
            for difference in server_differences(entry, server)
        )
        if control.mechanism in CONFIG_CHECKED:
            reason = control_problem(
                repo_root,
                control,
                url=entry.get("url", ""),
                args=entry.get("args", []),
            )
            if reason:
                checks.append(
                    DoctorCheck(
                        bundle.name,
                        "fail",
                        problem(
                            f"{bundle.name} breaks its {control.mechanism} control: {reason}",
                            restore,
                            file=label,
                        ),
                    )
                )
    return checks


def _deny_checks(
    clients: ClientConfigs,
    bundle: Bundle,
    server: ServerDefinition,
    conflicts: list[Client],
) -> list[DoctorCheck]:
    missing: list[tuple[str, str]] = []
    claude = [*deny_rules(clients.claude_local_settings), *clients.claude_shared_deny]
    cursor = deny_rules(clients.cursor_permissions)
    if "claude" not in conflicts:
        missing += [
            (CLAUDE_LOCAL_SETTINGS, r)
            for r in claude_deny_rules(server)
            if r not in claude
        ]
    if "cursor" not in conflicts:
        missing += [
            (CURSOR_PERMISSIONS, r)
            for r in cursor_deny_rules(server)
            if r not in cursor
        ]
    entry = clients.server_entry("codex", server.server_name)
    if entry is not None and "codex" not in conflicts:
        disabled: list[str] = entry.get("disabled_tools", [])
        missing += [(CODEX_CONFIG, t) for t in server.write_tools if t not in disabled]
    return [
        DoctorCheck(
            bundle.name,
            "fail",
            problem(f"does not deny {rule}", "run `research setup`", file=label),
        )
        for label, rule in missing
    ]


def _check_bundle(
    repo_root: Path, clients: ClientConfigs, bundle: Bundle, owned: list[Client]
) -> list[DoctorCheck]:
    control = bundle.spec.read_only_control
    checks: list[DoctorCheck] = []
    if bundle.server is not None:
        checks += _client_checks(repo_root, clients, bundle, bundle.server, owned)
        checks += _deny_checks(
            clients, bundle, bundle.server, clients.conflicts(bundle.server, owned)
        )
    if control.mechanism not in CONFIG_CHECKED:
        checks.append(
            DoctorCheck(
                bundle.name,
                "declared",
                f"{control.mechanism}: {control.detail}. Config cannot prove this; "
                f"run `research source show {bundle.name}`.",
            )
        )
    elif not checks:
        checks.append(
            DoctorCheck(bundle.name, "pass", f"{control.mechanism}: {control.detail}")
        )
    return checks


def _connector_checks(repo_root: Path, clients: ClientConfigs) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    for name, rules in connector_deny_rules(repo_root).items():
        missing = [rule for rule in rules if rule not in clients.claude_shared_deny]
        if missing:
            more = f" and {len(missing) - 1} more" if len(missing) > 1 else ""
            checks.append(
                DoctorCheck(
                    name,
                    "fail",
                    problem(
                        f"does not deny {missing[0]}{more}",
                        "run `research setup`, then commit the file",
                        file=CLAUDE_SETTINGS,
                    ),
                )
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
            problem(
                f"native goals are {state}",
                "set `goals = true` under `[features]`",
                file=CODEX_CONFIG,
            ),
        )
    ]


def _leftover_checks(
    repo_root: Path, clients: ClientConfigs, ledger: dict[str, Wiring]
) -> list[DoctorCheck]:
    """Report what research added for a source that no longer wants it."""
    document = load_sources_file(repo_root)
    checks: list[DoctorCheck] = []
    for name, wiring in ledger.items():
        if not wiring_is_unwanted(repo_root, document, name, wiring):
            continue
        files = [
            CLIENT_FILES[client]
            for client in wiring.clients
            if clients.server_entry(client, wiring.server_name)
        ]
        checks.extend(
            DoctorCheck(
                name,
                "fail",
                problem(
                    f"server '{wiring.server_name}' is left over from source {name}, "
                    "which no longer wants it",
                    "run `research setup`",
                    file=file,
                ),
            )
            for file in files or [WIRING_FILE]
        )
    return checks


def run_doctor(repo_root: Path) -> list[DoctorCheck]:
    bundles, without_bundle = enabled_bundles(repo_root)
    try:
        clients = ClientConfigs.read(repo_root)
        ledger = owned_wiring(repo_root)
    except SourceConfigError as exc:
        return [DoctorCheck("client config", "fail", str(exc))]
    checks = [
        *_goals_checks(repo_root, clients),
        *_connector_checks(repo_root, clients),
    ]
    checks.extend(
        check
        for bundle in bundles
        for check in _check_bundle(
            repo_root,
            clients,
            bundle,
            ledger[bundle.name].clients if bundle.name in ledger else [],
        )
    )
    checks.extend(_leftover_checks(repo_root, clients, ledger))
    checks.extend(
        DoctorCheck(
            name,
            "declared",
            problem(
                f"{name} has no bundle, so nothing can be checked",
                f"run `research source new {name}`",
                file="config/sources.json",
            ),
        )
        for name in without_bundle
    )
    return checks
