"""Edit hooks for each agent client, generated from one table.

Each client runs `report-edit.sh` after an edit. A hook reports a problem and never blocks.
Client hook files belong to the user, so setup adds only its own missing entry.

Each client's shape follows its published docs. None has been run against a live client here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import JsonValue, TypeAdapter, ValidationError

from .client_configs import CLAUDE_SETTINGS, JsonObject, read_json_object
from .feedback import problem
from .io import write_documents
from .layout import as_table
from .sources import Client, SourceConfigError

HOOK_SCRIPT = ".agents/hooks/report-edit.sh"
REPORT_LIMIT = 2000
PATCH_FILE = re.compile(r"(?m)^\*\*\* (?:Add|Update) File: (.+)$")
_HOOK_INPUT = TypeAdapter(dict[str, JsonValue])


@dataclass(frozen=True)
class ClientHook:
    file: str
    event: str
    matcher: str
    root: str


CLIENT_HOOKS: dict[Client, ClientHook] = {
    "claude": ClientHook(CLAUDE_SETTINGS, "PostToolUse", "Edit|Write", '"$CLAUDE_PROJECT_DIR"/'),
    "codex": ClientHook(
        ".codex/hooks.json",
        "PostToolUse",
        "Edit|Write",
        '"$(git rev-parse --show-toplevel)"/',
    ),
    # Cursor documents `additional_context` on `postToolUse`, and no output on `afterFileEdit`.
    "cursor": ClientHook(".cursor/hooks.json", "postToolUse", "Write", ""),
}


def _entry(client: Client, hook: ClientHook) -> JsonObject:
    command = f"sh {hook.root}{HOOK_SCRIPT} {client}"
    if client == "cursor":
        return {"command": command, "matcher": hook.matcher}
    return {"matcher": hook.matcher, "hooks": [{"type": "command", "command": command}]}


def _with_hook(document: JsonObject, client: Client, hook: ClientHook) -> str | None:
    """Bring the client's entry up to date, and say what changed, if anything."""
    if client == "cursor":
        document.setdefault("version", 1)
    hooks = document.setdefault("hooks", {})
    entries = hooks.setdefault(hook.event, []) if isinstance(hooks, dict) else None
    if not isinstance(entries, list):
        raise SourceConfigError(
            problem(
                f"hooks.{hook.event} is not a list",
                f"make it a list, so `research setup` can add its entry to {hook.file}",
                file=hook.file,
            )
        )
    entry = _entry(client, hook)
    if entry in entries:
        return None
    entries.append(entry)
    return f"added the edit hook to {hook.file}"


def install_hooks(repo_root: Path) -> list[str]:
    documents: dict[Path, str] = {}
    actions: list[str] = []
    for client, hook in CLIENT_HOOKS.items():
        path = repo_root / hook.file
        document = read_json_object(path) if path.exists() else {}
        action = _with_hook(document, client, hook)
        if action is not None:
            documents[path] = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
            actions.append(action)
    write_documents(documents)
    return actions


def edited_files(hook_input: str, repo_root: Path) -> list[str]:
    """Return the repo paths in a client's hook JSON: Claude, Cursor, or a Codex patch.

    A file outside the repo is not this repo's to format or report on.
    """
    try:
        document = _HOOK_INPUT.validate_json(hook_input)
    except ValidationError:
        return []
    cwd = document.get("cwd")
    base = Path(cwd) if isinstance(cwd, str) else Path.cwd()
    root = repo_root.resolve()
    tool_input = as_table(document.get("tool_input"))
    direct = [tool_input.get("file_path"), document.get("file_path")]
    patch = tool_input.get("command")
    patched = PATCH_FILE.findall(patch) if isinstance(patch, str) else []
    named = [
        *(path for path in direct if isinstance(path, str)),
        *cast("list[str]", patched),
    ]
    resolved = [(base / path).resolve() for path in named]
    return [str(path) for path in resolved if path.is_relative_to(root)]


def hook_report(client: Client, text: str) -> str:
    """Wrap a report in the JSON that puts it in front of the client's agent."""
    if len(text) > REPORT_LIMIT:
        text = (
            f"{text[:REPORT_LIMIT]}\n{len(text) - REPORT_LIMIT} more characters. "
            f"See all of it: sh {HOOK_SCRIPT}"
        )
    if client == "cursor":
        return json.dumps({"additional_context": text})
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": text,
            }
        }
    )
