from __future__ import annotations

import json
import tomllib
from pathlib import Path

from agentic_research_loop.cli import main
from agentic_research_loop.repo_setup import PACKAGED_SKILLS, link_skills

ROOT = Path(__file__).resolve().parents[1]


def _consumer(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'consumer'\n\n[tool.agentic-research-loop]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_setup_gives_a_consumer_repo_skills_and_configs(tmp_path, monkeypatch) -> None:
    repo = _consumer(tmp_path, monkeypatch)
    assert main(["source", "enable", "stripe"]) == 0
    (repo / ".mcp.json").unlink()

    assert main(["setup"]) == 0

    assert "stripe" in json.loads((repo / ".mcp.json").read_text())["mcpServers"]
    assert tomllib.loads((repo / ".codex" / "config.toml").read_text())["features"][
        "goals"
    ]
    skill = repo / ".agents" / "skills" / "research-goal" / "SKILL.md"
    assert skill.read_text(encoding="utf-8").startswith("---\nname: research-goal")
    assert (repo / ".claude" / "skills" / "research-goal" / "SKILL.md").exists()


def test_skill_links_are_relative(tmp_path, monkeypatch) -> None:
    repo = _consumer(tmp_path, monkeypatch)

    link_skills(repo)

    assert not (repo / ".agents" / "skills" / "research-goal").readlink().is_absolute()


def test_second_setup_reports_and_changes_nothing(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = _consumer(tmp_path, monkeypatch)
    main(["source", "enable", "stripe"])
    main(["setup"])
    before = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    capsys.readouterr()

    assert main(["setup"]) == 0

    assert capsys.readouterr().out == "- nothing to do\n"
    assert {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()} == before


def test_setup_reports_a_restored_server_and_deny_list(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = _consumer(tmp_path, monkeypatch)
    main(["source", "enable", "stripe"])
    (repo / ".cursor" / "mcp.json").write_text('{"mcpServers": {}}')
    (repo / ".claude" / "settings.json").write_text("{}")
    capsys.readouterr()

    assert main(["setup"]) == 0

    output = capsys.readouterr().out
    assert "wired server 'stripe' in .cursor/mcp.json" in output
    assert ".mcp.json" not in output
    assert "denied 4 write tools" in output


def test_package_declares_its_types() -> None:
    assert (PACKAGED_SKILLS.parent / "py.typed").exists()


def test_setup_keeps_a_local_skill(tmp_path, monkeypatch) -> None:
    repo = _consumer(tmp_path, monkeypatch)
    local = repo / ".agents" / "skills" / "research-goal"
    local.mkdir(parents=True)
    (local / "SKILL.md").write_text("mine\n", encoding="utf-8")

    link_skills(repo)

    assert (local / "SKILL.md").read_text(encoding="utf-8") == "mine\n"


def test_committed_skill_links_point_into_the_package() -> None:
    for name in ("research-goal", "research-spec"):
        link = ROOT / ".agents" / "skills" / name
        assert link.resolve() == (PACKAGED_SKILLS / name).resolve()


def test_setup_keeps_a_users_symlinked_skill(tmp_path, monkeypatch) -> None:
    repo = _consumer(tmp_path, monkeypatch)
    mine = repo / "my-skill"
    mine.mkdir()
    link = repo / ".agents" / "skills" / "research-goal"
    link.parent.mkdir(parents=True)
    link.symlink_to(mine)

    link_skills(repo)

    assert link.resolve() == mine.resolve()


def test_setup_repoints_a_stale_engine_link(tmp_path, monkeypatch) -> None:
    repo = _consumer(tmp_path, monkeypatch)
    link = repo / ".agents" / "skills" / "research-goal"
    link.parent.mkdir(parents=True)
    link.symlink_to("../../.venv-old/agentic_research_loop/skills/research-goal")

    link_skills(repo)

    assert link.resolve() == (PACKAGED_SKILLS / "research-goal").resolve()
