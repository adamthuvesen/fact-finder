"""Enable and disable opt-in source bundles.

A bundle is a directory holding `source.json`, `SETUP.md`, and for an MCP server
`mcp.snippet.json`. Bundles ship inside this package. A repo can add its own under
`examples/sources/`, and a repo bundle wins over a packaged one of the same name.

`config/sources.json` is the source of truth. It records each enabled source and what
the engine added to the client files. It is written first, and a failed write restores
every file, so a failure leaves the previous consistent state.

`.mcp.json` is tracked in this repo, so enabling a bundle dirties it. Do not commit
enabled configs back here: this repo ships neutral.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from .client_configs import ClientConfigs
from .io import read_text, write_documents
from .sources import (
    NAME_PATTERN,
    ServerDefinition,
    SourceConfigError,
    SourcesFile,
    SourceSpec,
    load_sources_file,
    parse_sources_file,
    render_sources_file,
    user_sources_path,
)

PACKAGED_BUNDLES = Path(__file__).parent / "bundles"
REPO_BUNDLES = ("examples", "sources")


@dataclass(frozen=True)
class Bundle:
    name: str
    path: Path
    spec: SourceSpec
    server: ServerDefinition | None


def _bundle_roots(repo_root: Path) -> list[Path]:
    return [repo_root.joinpath(*REPO_BUNDLES), PACKAGED_BUNDLES]


def available_bundles(repo_root: Path) -> list[str]:
    return sorted(
        {
            entry.parent.name
            for root in _bundle_roots(repo_root)
            for entry in root.glob("*/source.json")
        }
    )


def _bundle_path(repo_root: Path, name: str) -> Path:
    if not NAME_PATTERN.match(name):
        raise SourceConfigError(
            f"Invalid bundle name {name!r}; use lowercase letters, digits, '-' or '_'."
        )
    for root in _bundle_roots(repo_root):
        if (root / name / "source.json").is_file():
            return root / name
    available = ", ".join(available_bundles(repo_root)) or "(none)"
    raise SourceConfigError(f"No bundle {name!r}. Available: {available}")


def load_bundle(repo_root: Path, name: str) -> Bundle:
    path = _bundle_path(repo_root, name)
    sources = parse_sources_file(read_text(path / "source.json"), f"{name}/source.json")
    if list(sources) != [name]:
        raise SourceConfigError(
            f"{name}/source.json must define exactly the source {name!r}."
        )
    server = None
    server_path = path / "mcp.snippet.json"
    if server_path.is_file():
        try:
            server = ServerDefinition.model_validate_json(read_text(server_path))
        except ValidationError as exc:
            raise SourceConfigError(
                f"{name}/mcp.snippet.json is invalid: {exc.errors()[0]['msg']}"
            ) from exc
    return Bundle(name=name, path=path, spec=sources[name], server=server)


def _support_files(repo_root: Path, bundle: Bundle) -> dict[Path, str]:
    """Return a server's support files for `config/`, keeping any local edit."""
    documents: dict[Path, str] = {}
    for file_name in bundle.server.support_files if bundle.server else []:
        target = repo_root / "config" / file_name
        if not target.exists():
            documents[target] = read_text(bundle.path / file_name)
    return documents


def _sources_document(repo_root: Path, document: SourcesFile) -> dict[Path, str]:
    """Return the source of truth when it changed. No sources needs no file."""
    path = user_sources_path(repo_root)
    content = render_sources_file(document)
    if path.exists() and read_text(path) == content:
        return {}
    return {path: content} if path.exists() or document.sources else {}


def wire_clients(
    repo_root: Path, document: SourcesFile, bundles: list[Bundle]
) -> list[str]:
    """Add `bundles` to every client and record it, or change nothing on any error.

    The returned actions name real changes only, so a no-op reports nothing.
    """
    clients = ClientConfigs.read(repo_root)
    actions: list[str] = []
    if clients.goals_state() == "unset":
        clients.enable_codex_goals()
        actions.append("enabled native goals in .codex/config.toml")
    support: dict[Path, str] = {}
    for bundle in bundles:
        support |= _support_files(repo_root, bundle)
        if bundle.server is None:
            continue
        name = bundle.server.server_name
        result = clients.wire(bundle.server, document.wiring.get(bundle.name))
        document.wiring[bundle.name] = result.wiring
        if result.added_files:
            actions.append(f"wired server '{name}' in {', '.join(result.added_files)}")
        if result.denied:
            actions.append(
                f"denied {len(bundle.server.write_tools)} write tools of '{name}'"
            )
    actions.extend(f"copied {path.name} to config/" for path in support)
    write_documents(
        {
            **_sources_document(repo_root, document),
            **clients.documents(),
            **support,
        }
    )
    return actions


def enable_bundle(repo_root: Path, name: str) -> list[str]:
    bundle = load_bundle(repo_root, name)
    document = load_sources_file(repo_root)
    previous = document.sources.get(name)
    document.sources[name] = bundle.spec
    actions = wire_clients(repo_root, document, [bundle])
    if previous != bundle.spec:
        verb = "updated" if previous else "added"
        actions.insert(0, f"{verb} source '{name}' in config/sources.json")
    return [
        *actions,
        f"next: follow {bundle.path / 'SETUP.md'} for credentials and read-only setup",
    ]


def disable_bundle(repo_root: Path, name: str) -> list[str]:
    """Remove only what enable added. A server enable never added stays in place."""
    document = load_sources_file(repo_root)
    if name not in document.sources:
        return []
    del document.sources[name]
    wiring = document.wiring.pop(name, None)
    clients = ClientConfigs.read(repo_root)
    if wiring is not None:
        clients.unwire(wiring)
    write_documents(
        {
            user_sources_path(repo_root): render_sources_file(document),
            **clients.documents(),
        }
    )
    actions = [f"removed source '{name}' from config/sources.json"]
    if wiring is not None:
        actions.append(f"removed server '{wiring.server_name}' from all client configs")
    return actions


def enabled_bundles(repo_root: Path) -> tuple[list[Bundle], list[str]]:
    """Return the bundles behind enabled sources, and enabled sources with no bundle."""
    known = set(available_bundles(repo_root))
    names = sorted(load_sources_file(repo_root).sources)
    return (
        [load_bundle(repo_root, name) for name in names if name in known],
        [name for name in names if name not in known],
    )


def sql_backed_families(repo_root: Path) -> set[str]:
    """Return every known source whose spec says it answers through SQL."""
    specs = {
        **{
            name: load_bundle(repo_root, name).spec
            for name in available_bundles(repo_root)
        },
        **load_sources_file(repo_root).sources,
    }
    return {name for name, spec in specs.items() if spec.sql_backed}


def render_bundle_list(repo_root: Path) -> str:
    names = available_bundles(repo_root)
    if not names:
        return "No source bundles found."
    enabled = load_sources_file(repo_root).sources
    width = max(len(name) for name in names)
    lines = ["Source bundles (* = enabled):", ""]
    for name in names:
        spec = load_bundle(repo_root, name).spec
        mark = "*" if name in enabled else " "
        lines.append(
            f"  {mark} {name:<{width}}  {spec.transport:<11}  "
            f"{spec.read_only_control.mechanism}: {spec.read_only_control.detail}"
        )
    return "\n".join(lines)
