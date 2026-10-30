"""`research setup`: one command that makes a repo ready to run research."""

from __future__ import annotations

from pathlib import Path

from .source_bundles import enabled_bundles, wire_clients
from .sources import load_sources_file

PACKAGED_SKILLS = Path(__file__).parent / "skills"
SKILLS_DIR = (".agents", "skills")


def _is_engine_link(link: Path) -> bool:
    """Recognize a link to an older install of this package, such as a rebuilt venv."""
    return (
        link.readlink().as_posix().endswith(f"agentic_research_loop/skills/{link.name}")
    )


def link_skills(repo_root: Path) -> list[str]:
    """Link each packaged skill into `.agents/skills`, leaving a local skill alone."""
    skills_dir = repo_root.joinpath(*SKILLS_DIR)
    skills_dir.mkdir(parents=True, exist_ok=True)
    actions: list[str] = []
    for source in sorted(path for path in PACKAGED_SKILLS.iterdir() if path.is_dir()):
        link = skills_dir / source.name
        if link.is_symlink() and link.resolve() == source.resolve():
            continue
        if link.is_symlink() and _is_engine_link(link):
            link.unlink()
        elif link.is_symlink() or link.exists():
            continue
        link.symlink_to(
            source.resolve().relative_to(skills_dir.resolve(), walk_up=True)
        )
        actions.append(f"linked skill {source.name} into .agents/skills")
    return actions


def link_claude_skills(repo_root: Path) -> list[str]:
    """Point `.claude/skills` at `.agents/skills`, the path Claude Code reads."""
    link = repo_root / ".claude" / "skills"
    if link.exists() or link.is_symlink():
        return []
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(Path("..").joinpath(*SKILLS_DIR))
    return ["linked .claude/skills to .agents/skills"]


def setup_repo(repo_root: Path) -> list[str]:
    bundles, _ = enabled_bundles(repo_root)
    return [
        *wire_clients(repo_root, load_sources_file(repo_root), bundles),
        *link_skills(repo_root),
        *link_claude_skills(repo_root),
    ]
