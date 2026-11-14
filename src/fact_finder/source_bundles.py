"""Enable and disable opt-in source bundles.

A bundle is one `<name>.toml`: what the source is, how it stays read-only, its server, and
its setup steps. Bundles ship inside this package. A repo adds or overrides its own in
`sources_dir` under `[tool.fact-finder]`, by default `examples/sources/`.

`config/sources.json` names the sources a repo wants, and may be shared. `.research/wiring.json`
is local, and says what research added to this machine's client files. `reconcile_clients` is the
one path that brings those files in line with both, for every command that changes them. It writes
the source of truth first, and a failed write restores every file.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from pydantic import TypeAdapter, ValidationError

from .client_configs import ClientConfigs
from .feedback import problem, validation_problems
from .io import read_text, write_documents, write_text
from .layout import project_setting
from .sources import (
    BUILTIN_SOURCES,
    NAME_FIX,
    NAME_PATTERN,
    USER_SOURCES_FILE,
    BundleFile,
    Category,
    Connector,
    Mechanism,
    ServerDefinition,
    SourceConfigError,
    SourcesFile,
    SourceSpec,
    Transport,
    Wiring,
    load_sources_file,
    render_sources_file,
    user_sources_path,
)

PACKAGED_BUNDLES = Path(__file__).parent / "bundles"
DEFAULT_SOURCES_DIR = "examples/sources"
TODO = "TODO"
WIRING_FILE = ".research/wiring.json"
_WIRING_FILE = TypeAdapter(dict[str, Wiring])


@dataclass(frozen=True)
class Bundle:
    name: str
    path: Path
    spec: SourceSpec
    server: ServerDefinition | None
    setup: str
    connectors: list[Connector]


def repo_sources_dir(repo_root: Path) -> Path:
    relative = project_setting(repo_root, "sources_dir") or DEFAULT_SOURCES_DIR
    path = (repo_root / relative).resolve()
    if not path.is_relative_to(repo_root.resolve()):
        raise SourceConfigError(
            problem(
                f"sources_dir {relative} is outside the repo",
                "use a path inside the repo",
                file="pyproject.toml",
            )
        )
    return path


def _bundle_roots(repo_root: Path) -> list[Path]:
    return [repo_sources_dir(repo_root), PACKAGED_BUNDLES]


def available_bundles(repo_root: Path) -> list[str]:
    return sorted(
        {entry.stem for root in _bundle_roots(repo_root) for entry in root.glob("*.toml")}
    )


def _bundle_path(repo_root: Path, name: str) -> Path:
    if not NAME_PATTERN.match(name):
        raise SourceConfigError(problem(f"invalid bundle name {name!r}", NAME_FIX))
    for root in _bundle_roots(repo_root):
        if (root / f"{name}.toml").is_file():
            return root / f"{name}.toml"
    available = ", ".join(available_bundles(repo_root)) or "(none)"
    raise SourceConfigError(
        problem(
            f"no bundle {name!r}",
            f"use one of {available}, or run `research source new {name}`",
        )
    )


def load_bundle(repo_root: Path, name: str) -> Bundle:
    path = _bundle_path(repo_root, name)
    text = read_text(path)
    try:
        document = BundleFile.model_validate(tomllib.loads(text))
    except tomllib.TOMLDecodeError as exc:
        raise SourceConfigError(
            problem(f"not valid TOML: {exc}", "correct the syntax", file=str(path))
        ) from exc
    except ValidationError as exc:
        raise SourceConfigError("\n".join(validation_problems(exc, str(path), text))) from exc
    return Bundle(
        name=name,
        path=path,
        spec=document.source,
        server=document.server,
        setup=document.setup,
        connectors=document.connectors,
    )


def connector_deny_rules(repo_root: Path) -> dict[str, list[str]]:
    """Return the claude.ai connector rules of every bundle, enabled or not, by bundle.

    A person may connect a connector whatever sources a repo enables, so every bundle counts.
    """
    rules: dict[str, list[str]] = {}
    for name in available_bundles(repo_root):
        bundle = load_bundle(repo_root, name)
        server_tools = bundle.server.write_tools if bundle.server else []
        if bundle.connectors:
            rules[name] = [
                f"mcp__claude_ai_{connector.name}__{tool}"
                for connector in bundle.connectors
                for tool in connector.write_tools or server_tools
            ]
    return rules


def unfilled_fields(path: Path) -> list[str]:
    """Report each scaffold mark left in a bundle. Comments may mention the mark."""
    return [
        problem(
            f"still marked {TODO}: {line.strip()[:70]}",
            "replace the mark with the real value",
            file=str(path),
            line=number,
        )
        for number, line in enumerate(read_text(path).splitlines(), start=1)
        if TODO in line and not line.lstrip().startswith("#")
    ]


def _support_files(repo_root: Path, bundle: Bundle) -> dict[Path, str]:
    """Return a server's support files for `config/`, keeping any local edit."""
    documents: dict[Path, str] = {}
    for file_name, content in (bundle.server.support_files if bundle.server else {}).items():
        target = repo_root / "config" / file_name
        if not target.exists():
            documents[target] = f"{content}\n"
    return documents


def _sources_document(repo_root: Path, document: SourcesFile) -> dict[Path, str]:
    """Return the source of truth when it changed. No sources needs no file."""
    path = user_sources_path(repo_root)
    content = render_sources_file(document)
    if path.exists() and read_text(path) == content:
        return {}
    return {path: content} if path.exists() or document.sources else {}


def owned_wiring(repo_root: Path) -> dict[str, Wiring]:
    """Return what research added to this machine's client files, by source."""
    path = repo_root / WIRING_FILE
    if not path.exists():
        return {}
    text = read_text(path)
    try:
        return _WIRING_FILE.validate_json(text)
    except ValidationError as exc:
        raise SourceConfigError("\n".join(validation_problems(exc, WIRING_FILE, text))) from exc


def wiring_is_unwanted(repo_root: Path, document: SourcesFile, name: str, wiring: Wiring) -> bool:
    if name not in document.sources:
        return True
    if name not in available_bundles(repo_root):
        return False
    server = load_bundle(repo_root, name).server
    return server is None or server.server_name != wiring.server_name


def _wiring_documents(repo_root: Path, ledger: dict[str, Wiring]) -> dict[Path, str]:
    """Return the local ownership record. Its folder ignores itself in git."""
    path = repo_root / WIRING_FILE
    if not ledger and not path.exists():
        return {}
    content = _WIRING_FILE.dump_json(ledger, indent=2).decode() + "\n"
    documents = {path.parent / ".gitignore": "*\n"}
    if not path.exists() or read_text(path) != content:
        documents[path] = content
    return documents


def conflict_problem(server_name: str, source: str, file: str) -> str:
    return problem(
        f"server '{server_name}' exists, research did not add it, and it differs from "
        "its bundle. It stays as it is",
        f"make it match `research source show {source}`, or rename or remove it, then run "
        "`research setup`",
        file=file,
    )


def reconcile_clients(repo_root: Path, document: SourcesFile) -> list[str]:
    """Bring local client files in line with `document` and the bundles, or change nothing on error.

    It removes what research added that no source wants, and adds or updates what one does.
    A person's own entry is never changed, and one that conflicts blocks only its own client.
    The returned actions name real changes, plus one problem for each such conflict.
    """
    clients = ClientConfigs.read(repo_root)
    ledger = owned_wiring(repo_root)
    actions: list[str] = []
    if clients.goals_state() == "unset":
        clients.enable_codex_goals()
        actions.append("enabled native goals in .codex/config.toml")
    for name, wiring in list(ledger.items()):
        if wiring_is_unwanted(repo_root, document, name, wiring):
            clients.unwire(wiring)
            del ledger[name]
            actions.append(f"removed server '{wiring.server_name}' from all client configs")
    known = set(available_bundles(repo_root))
    support: dict[Path, str] = {}
    for name in sorted(set(document.sources) & known):
        bundle = load_bundle(repo_root, name)
        support |= _support_files(repo_root, bundle)
        if bundle.server is None:
            continue
        server_name = bundle.server.server_name
        result = clients.wire(bundle.server, ledger.get(name))
        ledger[name] = result.wiring
        if result.added_files:
            actions.append(f"wired server '{server_name}' in {', '.join(result.added_files)}")
        if result.updated_files:
            actions.append(
                f"updated server '{server_name}' to match its bundle in "
                f"{', '.join(result.updated_files)}"
            )
        if result.denied:
            actions.append(
                f"denied {len(bundle.server.write_tools)} write tools of '{server_name}'"
            )
        actions.extend(conflict_problem(server_name, name, file) for file in result.conflict_files)
    actions.extend(f"copied {path.name} to config/" for path in support)
    connector_rules = [rule for rules in connector_deny_rules(repo_root).values() for rule in rules]
    if added := clients.deny_in_shared_settings(connector_rules):
        actions.append(
            f"denied {len(added)} claude.ai connector write tools in .claude/settings.json"
        )
    write_documents(
        {
            **_sources_document(repo_root, document),
            **_wiring_documents(repo_root, ledger),
            **clients.documents(),
            **support,
        }
    )
    return actions


def enable_bundle(repo_root: Path, name: str) -> list[str]:
    bundle = load_bundle(repo_root, name)
    unfilled = unfilled_fields(bundle.path)
    if unfilled:
        # A scaffold's control is not real yet, so wiring it would claim a read-only guard.
        raise SourceConfigError("\n".join(unfilled))
    document = load_sources_file(repo_root)
    added = name not in document.sources
    if added:
        document.sources.append(name)
    actions = reconcile_clients(repo_root, document)
    if added:
        actions.insert(0, f"added source '{name}' to config/sources.json")
    return [
        *actions,
        f"next: run `research source show {name}` for credentials and read-only setup",
    ]


def disable_bundle(repo_root: Path, name: str) -> list[str]:
    """Remove only what enable added. A server enable never added stays in place."""
    document = load_sources_file(repo_root)
    if name not in document.sources:
        return []
    document.sources.remove(name)
    return [
        f"removed source '{name}' from config/sources.json",
        *reconcile_clients(repo_root, document),
    ]


def enabled_bundles(repo_root: Path) -> tuple[list[Bundle], list[str]]:
    """Return the bundles behind enabled sources, and enabled sources with no bundle."""
    known = set(available_bundles(repo_root))
    names = sorted(load_sources_file(repo_root).sources)
    return (
        [load_bundle(repo_root, name) for name in names if name in known],
        [name for name in names if name not in known],
    )


def load_registry(repo_root: Path) -> dict[str, SourceSpec]:
    """Return the built-in sources and the spec of each enabled source, from its bundle."""
    bundles, without_bundle = enabled_bundles(repo_root)
    if without_bundle:
        raise SourceConfigError(
            problem(
                f"enabled source {without_bundle[0]!r} has no bundle",
                f"run `research source new {without_bundle[0]}`, or remove it",
                file=USER_SOURCES_FILE,
            )
        )
    return {**BUILTIN_SOURCES, **{bundle.name: bundle.spec for bundle in bundles}}


def sql_backed_families(repo_root: Path) -> set[str]:
    """Return every known source whose spec says it answers through SQL."""
    return {
        name
        for name in available_bundles(repo_root)
        if load_bundle(repo_root, name).spec.sql_backed
    }


def render_bundle_list(repo_root: Path) -> str:
    names = available_bundles(repo_root)
    if not names:
        return "No source bundles found."
    enabled = load_sources_file(repo_root).sources
    width = max(len(name) for name in names)
    lines = ["Source bundles (* = enabled). Details: research source show <name>", ""]
    for name in names:
        spec = load_bundle(repo_root, name).spec
        mark = "*" if name in enabled else " "
        lines.append(
            f"  {mark} {name:<{width}}  {spec.transport:<11}  "
            f"{spec.read_only_control.mechanism}: {spec.read_only_control.detail}"
        )
    return "\n".join(lines)


def render_bundle(repo_root: Path, name: str) -> str:
    bundle = load_bundle(repo_root, name)
    control = bundle.spec.read_only_control
    denied = bundle.server.write_tools if bundle.server else []
    return "\n".join(
        [
            f"{bundle.spec.display_name} ({name}), {bundle.spec.category}, {bundle.spec.transport}",
            f"File: {bundle.path}",
            f"Read-only control: {control.mechanism}: {control.detail}",
            *([f"Denied write tools: {', '.join(denied)}"] if denied else []),
            "",
            bundle.spec.plan_line,
            bundle.spec.notes,
            "",
            bundle.setup,
        ]
    )


def _choices(values: tuple[str, ...]) -> str:
    return ", ".join(values)


def scaffold_bundle(repo_root: Path, name: str) -> list[str]:
    """Write a loadable bundle. Enable refuses it until every TODO is replaced."""
    if not NAME_PATTERN.match(name):
        raise SourceConfigError(problem(f"invalid bundle name {name!r}", NAME_FIX))
    path = repo_sources_dir(repo_root) / f"{name}.toml"
    if path.exists():
        raise SourceConfigError(
            problem(
                "the bundle already exists",
                f"edit it, or run `research source show {name}`",
                file=str(path),
            )
        )
    control_todo = f"{TODO}: the read-only credential scope {name} needs"
    write_text(
        path,
        f'''# Replace each {TODO}. `research lint {path.relative_to(repo_root.resolve())}` lists what is left, and
# `research source enable {name}` refuses this file until none are left.
setup = """
{control_todo}.

{TODO}: how to get a credential that has only this scope.
"""

[source]
display_name = {json.dumps(name.replace("-", " ").title())}
# One of: {_choices(get_args(Category))}
category = "work-context"
# One of: {_choices(get_args(Transport))}
transport = "cli"
plan_line = "{TODO}: one line saying what a case uses {name} for."
notes = "{TODO}: what {name} is good for, and a reminder that it is read-only."
# Set to true if this source answers through SQL, so a case must preserve its queries.
sql_backed = false

[source.read_only_control]
# One of: {_choices(get_args(Mechanism))}
# `research doctor` proves url_suffix, server_flag, arg_absent, and statement_allowlist from
# config. It only reports the others as declared, and `setup` must name their detail.
mechanism = "credential_scope"
detail = "{control_todo}"

# For an MCP server, add this and change `transport`. Set exactly one of url or command.
# [server]
# server_name = "{name}"
# url = "https://example.com/mcp/readonly"
# write_tools = ["tool_that_writes"]

# For each claude.ai connector to the same service, add one. `research setup` denies its
# write tools in .claude/settings.json. Omit write_tools when they match [server].
# [[connectors]]
# name = "{name.replace("-", " ").title().replace(" ", "_")}"
# write_tools = ["tool_that_writes"]
''',
    )
    load_bundle(repo_root, name)
    return [
        f"created {path}",
        f"next: replace each {TODO} there, then run `research source enable {name}`",
    ]
