"""`research setup`: one command that makes a repo ready to run research."""

from __future__ import annotations

from pathlib import Path

from .agent_hooks import install_hooks
from .source_bundles import reconcile_clients
from .sources import load_sources_file

PACKAGE = Path(__file__).parent
SKILLS_DIR = (".agents", "skills")


def _is_engine_link(link: Path, kind: str) -> bool:
    """Recognize a link to another install of this package, such as a rebuilt venv."""
    return link.readlink().as_posix().endswith(f"fact_finder/{kind}/{link.name}")


def _link_packaged(repo_root: Path, kind: str) -> list[str]:
    """Link each packaged entry of `kind` into `.agents/`, leaving a local one alone."""
    target_dir = repo_root / ".agents" / kind
    target_dir.mkdir(parents=True, exist_ok=True)
    actions: list[str] = []
    for source in sorted(path for path in (PACKAGE / kind).iterdir() if path.name != "__pycache__"):
        link = target_dir / source.name
        if link.is_symlink() and link.resolve() == source.resolve():
            continue
        if link.is_symlink() and _is_engine_link(link, kind):
            link.unlink()
        elif link.is_symlink() or link.exists():
            continue
        link.symlink_to(source.resolve().relative_to(target_dir.resolve(), walk_up=True))
        actions.append(f"linked {source.name} into .agents/{kind}")
    return actions


def link_skills(repo_root: Path) -> list[str]:
    return _link_packaged(repo_root, "skills")


def link_claude_skills(repo_root: Path) -> list[str]:
    """Point `.claude/skills` at `.agents/skills`, the path Claude Code reads."""
    link = repo_root / ".claude" / "skills"
    if link.exists() or link.is_symlink():
        return []
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(Path("..").joinpath(*SKILLS_DIR))
    return ["linked .claude/skills to .agents/skills"]


def setup_repo(repo_root: Path) -> list[str]:
    return [
        *reconcile_clients(repo_root, load_sources_file(repo_root)),
        *link_skills(repo_root),
        *link_claude_skills(repo_root),
        *_link_packaged(repo_root, "hooks"),
        *install_hooks(repo_root),
    ]
