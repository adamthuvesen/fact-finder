from __future__ import annotations

import json
from pathlib import Path

import pytest
from support.cases import fill_case

from fact_finder import research, templates
from fact_finder.cli import main
from fact_finder.research import resolve_case_path

CASE_FILES = (
    "brief.md",
    "notes.md",
    "report.md",
    "queries.sql",
    "source-objects.md",
    "plan.md",
)


def _init(repo_root: Path, slug: str, *extra: str) -> Path:
    assert main(["init", slug, *extra]) == 0
    return sorted((repo_root / "research").iterdir())[-1]


def test_init_creates_the_case_artifacts(repo_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(repo_root)

    case_path = _init(repo_root, "regional-comparison", "--template", "comparison")

    assert case_path.name.endswith("regional-comparison")
    for name in CASE_FILES:
        assert (case_path / name).exists(), name
    assert not (case_path / "evidence.json").exists()


def test_decision_init_scaffolds_the_evidence_manifest(repo_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(repo_root)

    case_path = _init(repo_root, "big-call", "--rigour", "decision")

    assert (case_path / "evidence.json").exists()
    assert "- Rigour: `decision`" in (case_path / "brief.md").read_text(encoding="utf-8")


def test_init_creates_no_machine_state(repo_root: Path, monkeypatch) -> None:
    """Case artifacts are the only durable record; the goal owns execution state."""
    monkeypatch.chdir(repo_root)

    case_path = _init(repo_root, "no-state", "--template", "exploration")

    assert not (case_path / "state").exists()
    assert not (case_path / "status.md").exists()


def test_init_points_at_the_goal_command(repo_root: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)

    _init(repo_root, "next-step", "--template", "exploration")

    assert "Next: uv run research next" in capsys.readouterr().out


def test_init_records_source_hint_in_the_brief(repo_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(repo_root)

    case_path = _init(
        repo_root, "onboarding-change", "--source-hint", "web-search=competitor launch"
    )

    brief = (case_path / "brief.md").read_text(encoding="utf-8")
    assert "competitor launch" in brief


def test_init_rejects_a_hint_for_a_source_it_does_not_allow(
    repo_root: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(repo_root)

    exit_code = main(["init", "hinted", "--local-only", "--source-hint", "web-search=x"])

    assert exit_code == 1
    assert "--source-hint names" in capsys.readouterr().err


def test_init_rejects_an_unknown_source(repo_root: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)

    assert main(["init", "unknown", "--sources", "nope"]) == 1
    assert "unknown source nope" in capsys.readouterr().err
    assert not (repo_root / "research").exists()


def test_init_is_atomic_when_a_write_fails(repo_root: Path, monkeypatch, capsys) -> None:
    """A half-written case looks real to `resolve_case_path`, so leave nothing."""
    monkeypatch.chdir(repo_root)
    real_write = research.write_text

    def fail_on_report(path: Path, content: str) -> None:
        if path.name == "report.md":
            raise OSError("disk full")
        real_write(path, content)

    monkeypatch.setattr(research, "write_text", fail_on_report)

    assert main(["init", "half-written"]) == 1

    assert "disk full" in capsys.readouterr().err
    assert list((repo_root / "research").iterdir()) == []


def test_init_refuses_a_research_directory_outside_the_repo(
    repo_root: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(repo_root)
    (repo_root / "research").symlink_to(tmp_path)

    assert main(["init", "escaped"]) == 1
    assert "resolves outside" in capsys.readouterr().err


def test_init_from_spec_uses_supplied_artifacts(repo_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(repo_root)
    spec = repo_root / "spec"
    spec.mkdir()
    (spec / "brief.md").write_text(
        "# Brief\n\n## Question\n\nWhy?\n\n## Scope\n\n- Research shape: `exploration`\n",
        encoding="utf-8",
    )
    (spec / "report.md").write_text("# Supplied report\n", encoding="utf-8")

    case_path = _init(repo_root, "from-spec", "--from-spec", str(spec), "--local-only")

    assert (case_path / "report.md").read_text(encoding="utf-8") == "# Supplied report\n"
    assert "## Allowed Source Families" in (case_path / "brief.md").read_text(encoding="utf-8")


def test_init_attaches_context_path(repo_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(repo_root)
    context_dir = repo_root / "context-pack"
    context_dir.mkdir()
    (context_dir / "notes.md").write_text("# Notes\n", encoding="utf-8")

    case_path = _init(
        repo_root,
        "onboarding-ctx",
        "--template",
        "exploration",
        "--context-path",
        str(context_dir),
    )

    brief = (case_path / "brief.md").read_text(encoding="utf-8")
    assert str(context_dir.resolve()) in brief


def test_init_rejects_missing_context_path(repo_root: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)

    exit_code = main(
        [
            "init",
            "missing-context",
            "--context-path",
            str(repo_root / "does-not-exist"),
        ]
    )

    assert exit_code == 1
    assert "--context-path" in capsys.readouterr().err


def test_init_uses_the_supplied_question(repo_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(repo_root)

    case_path = _init(
        repo_root,
        "specific-question",
        "--question",
        "Why did weekly exports fail more often in June?",
    )

    brief = (case_path / "brief.md").read_text(encoding="utf-8")
    assert "Why did weekly exports fail more often in June?" in brief


def test_goal_uses_absolute_paths_and_the_validation_gate(
    repo_root: Path, monkeypatch, capsys
) -> None:
    """A goal handed relative paths can write a correct answer into the wrong
    directory and still look finished. Every path in the contract is absolute."""
    monkeypatch.chdir(repo_root)
    case_path = _init(repo_root, "absolute-paths", "--rigour", "decision")
    capsys.readouterr()

    assert main(["goal", case_path.name]) == 0

    output = capsys.readouterr().out
    assert output.startswith("/goal ")
    assert str(case_path.resolve()) in output
    assert f'uv run research validate "{case_path.resolve()}" --strict' in output
    assert "independent subagent" in output
    assert f'research next "{case_path.resolve()}"' in output


def test_goal_names_the_cases_own_sources(repo_root: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)
    context_dir = repo_root / "local-pack"
    context_dir.mkdir()
    case_path = _init(
        repo_root,
        "scoped-sources",
        "--local-only",
        "--context-path",
        str(context_dir),
    )
    capsys.readouterr()

    main(["goal", case_path.name])

    output = capsys.readouterr().out
    assert str(context_dir.resolve()) in output
    assert "Web tools" not in output


def test_goal_resolves_a_short_slug(repo_root: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)
    _init(repo_root, "active-users-drop", "--template", "root-cause")
    capsys.readouterr()

    assert main(["goal", "active-users-drop"]) == 0
    assert capsys.readouterr().out.startswith("/goal ")


def test_validate_passes_on_a_fresh_case(repo_root: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)
    case_path = _init(repo_root, "fresh-case", "--template", "exploration")
    capsys.readouterr()

    assert main(["validate", case_path.name]) == 0
    assert "Validation passed" in capsys.readouterr().out


def test_validate_reports_a_missing_report(repo_root: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)
    case_path = _init(repo_root, "missing-artifact", "--template", "exploration")
    (case_path / "report.md").unlink()
    capsys.readouterr()

    assert main(["validate", case_path.name]) == 1
    assert "report.md: the file is missing" in capsys.readouterr().out


def test_resolve_case_path_ambiguous(repo_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(repo_root)
    research = repo_root / "research"
    research.mkdir(exist_ok=True)
    (research / "2026-01-01-foo").mkdir()
    (research / "2026-01-02-foo").mkdir()

    with pytest.raises(FileNotFoundError, match="matches"):
        resolve_case_path(repo_root, "foo")


def test_resolve_case_path_rejects_outside_short_slug_match(repo_root: Path) -> None:
    (repo_root / "research").mkdir()
    (repo_root / "src").mkdir()

    with pytest.raises(FileNotFoundError, match="outside"):
        resolve_case_path(repo_root, "../src")


def test_resolve_case_path_rejects_a_file_inside_research(repo_root: Path) -> None:
    (repo_root / "research").mkdir()
    (repo_root / "research" / "stray.md").write_text("x", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="outside"):
        resolve_case_path(repo_root, "stray.md")


def test_validate_json_reports_a_failure(repo_root: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)
    case_path = _init(repo_root, "json-failure")
    capsys.readouterr()

    assert main(["validate", case_path.name, "--strict", "--json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is False
    assert payload["strict"] is True
    assert payload["errors"]
    assert "cannot be proved" in payload["limits"]


def test_strict_pass_states_what_the_gate_cannot_prove(
    repo_root: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(repo_root)
    case = fill_case(repo_root / "research" / "2026-08-17-filled")

    assert main(["validate", case.name, "--strict"]) == 0

    assert "cannot be proved by a gate" in capsys.readouterr().out


def test_list_shows_each_case_with_its_status(repo_root: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)
    _init(repo_root, "scaffolded")
    fill_case(repo_root / "research" / "2026-08-17-filled")
    broken = repo_root / "research" / "2026-08-18-broken"
    broken.mkdir()
    (repo_root / "research" / ".2026-08-19-staging.abc").mkdir()
    capsys.readouterr()

    assert main(["list"]) == 0

    lines = dict(line.split() for line in capsys.readouterr().out.splitlines())
    assert lines["2026-08-17-filled"] == "decision-complete"
    assert lines["2026-08-18-broken"] == "invalid"
    assert next(v for k, v in lines.items() if k.endswith("scaffolded")) == "in-progress"
    assert not any(name.startswith(".") for name in lines)


def test_list_with_no_cases(repo_root: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)

    assert main(["list"]) == 0
    assert "No cases yet" in capsys.readouterr().out


def test_schema_prints_a_closed_schema(capsys) -> None:
    assert main(["schema", "review"]) == 0

    assert json.loads(capsys.readouterr().out)["additionalProperties"] is False


def test_review_snapshot_prints_hashes_and_approves_nothing(
    repo_root: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(repo_root)
    case_path = _init(repo_root, "snapshot", "--rigour", "decision")
    capsys.readouterr()

    assert main(["review-snapshot", case_path.name]) == 0

    assert "evidence.json" in json.loads(capsys.readouterr().out)
    assert not (case_path / "review.json").exists()


def test_a_missing_case_is_a_clean_error(repo_root: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)

    assert main(["goal", "no-such-case"]) == 1
    assert "no case" in capsys.readouterr().err


def test_outside_a_project_is_a_clean_error(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["list"]) == 1
    assert "[tool.fact-finder]" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["list", "doctor", "setup"])
def test_consumer_repo_is_recognized_by_its_tool_table(tmp_path, monkeypatch, command) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'consumer'\n\n[tool.fact-finder]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert main([command]) == 0


def test_validate_json_is_valid_for_a_missing_case(repo_root, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)

    assert main(["validate", "no-such-case", "--json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is False
    assert "no case" in payload["errors"][0]


def _root_cause_case_with_bad_plan(repo_root: Path) -> Path:
    case_path = _init(repo_root, "bad-plan", "--template", "root-cause")
    (case_path / "plan.md").write_bytes(b"\xff\xfe not utf8")
    return case_path


def test_validate_json_is_valid_for_a_non_utf8_report(repo_root, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)
    case_path = _root_cause_case_with_bad_plan(repo_root)
    capsys.readouterr()

    assert main(["validate", case_path.name, "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert any("plan.md" in item for item in payload["warnings"])
    (case_path / "report.md").write_bytes(b"\xff\xfe not utf8")
    assert main(["validate", case_path.name, "--json"]) == 1
    assert any("report.md" in item for item in json.loads(capsys.readouterr().out)["errors"])


def test_one_bad_case_does_not_abort_list(repo_root, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)
    bad = _init(repo_root, "bad-report")
    (bad / "report.md").write_bytes(b"\xff\xfe not utf8")
    deep = _init(repo_root, "deep-evidence", "--rigour", "decision")
    (deep / "evidence.json").write_text("[" * 1_000_000, encoding="utf-8")
    _init(repo_root, "fine")
    capsys.readouterr()

    assert main(["list"]) == 0

    lines = dict(line.split() for line in capsys.readouterr().out.splitlines())
    assert sorted(lines.values()) == ["in-progress", "in-progress", "invalid"]


def test_deep_evidence_snapshot_is_a_clean_error(repo_root, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)
    case_path = _init(repo_root, "deep-snapshot", "--rigour", "decision")
    (case_path / "evidence.json").write_text("[" * 1_000_000, encoding="utf-8")
    capsys.readouterr()

    assert main(["review-snapshot", case_path.name]) == 1

    assert "nested too deeply" in capsys.readouterr().err


@pytest.mark.parametrize("text", ["tool = 1\n", "project = 1\n", "[tool]\nfact-finder = 1\n"])
def test_malformed_project_tables_are_not_a_traceback(tmp_path, monkeypatch, text) -> None:
    (tmp_path / "pyproject.toml").write_text(text, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main(["list"]) in {0, 1}


@pytest.mark.parametrize(
    ("document", "text"),
    [("method", "# Research method"), ("evidence", "review-snapshot")],
)
def test_contract_prints_packaged_documents(tmp_path, monkeypatch, capsys, document, text) -> None:
    """A consumer has neither file in its tree, and needs no project root to read them."""
    monkeypatch.chdir(tmp_path)

    assert main(["contract", document]) == 0

    assert text in capsys.readouterr().out


def test_goal_points_at_the_contract(repo_root, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)
    case_path = _init(repo_root, "points")
    capsys.readouterr()

    main(["goal", case_path.name])

    assert "research contract method" in capsys.readouterr().out


def test_from_spec_scaffolds_a_missing_shape_and_question(repo_root, monkeypatch) -> None:
    monkeypatch.chdir(repo_root)
    spec = repo_root / "spec"
    spec.mkdir()
    (spec / "brief.md").write_text("# Brief\n\n## Scope\n\n- In scope: x\n", encoding="utf-8")

    case_path = _init(repo_root, "shapeless", "--from-spec", str(spec), "--question", "Why now?")

    assert main(["validate", case_path.name]) == 0
    brief = (case_path / "brief.md").read_text(encoding="utf-8")
    assert "- In scope: x\n- Research shape: `exploration`" in brief
    assert "Why now?" in brief


def test_from_spec_keeps_the_briefs_own_shape(repo_root, monkeypatch) -> None:
    monkeypatch.chdir(repo_root)
    spec = repo_root / "spec"
    spec.mkdir()
    (spec / "brief.md").write_text(
        "# Brief\n\n## Question\n\nWhy?\n\n## Scope\n\n- **Research shape:** `comparison`\n",
        encoding="utf-8",
    )

    case_path = _init(repo_root, "shaped", "--from-spec", str(spec), "--template", "root-cause")

    assert "root-cause" not in (case_path / "brief.md").read_text(encoding="utf-8")


def test_quick_answer_needs_very_little_ceremony(repo_root, monkeypatch, capsys) -> None:
    """Question to a passing, labelled answer: init, write report.md, validate."""
    monkeypatch.chdir(repo_root)
    case_path = _init(repo_root, "quick", "--question", "Did exports fail more in June?")
    report = case_path / "report.md"
    report.write_text(
        report.read_text(encoding="utf-8").replace(
            "<!-- research:placeholder --> Complete this section with the answer and the most "
            "decision-relevant evidence.",
            "Yes. Failures rose from 100 to 412 a week after the June 3 scheduler change.",
        ),
        encoding="utf-8",
    )
    capsys.readouterr()

    assert main(["validate", case_path.name, "--strict"]) == 0

    output = capsys.readouterr().out
    assert "Exploratory answer: no independent review." in output
    assert "Warnings:" in output
    assert "exploratory-complete" in (main(["list"]), capsys.readouterr().out)[1]


def test_accept_flag_records_and_labels(repo_root, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root)
    case = fill_case(repo_root / "research" / "2026-08-17-filled")
    (case / "review.json").unlink()
    capsys.readouterr()

    assert main(["validate", case.name, "--strict"]) == 1
    assert main(["validate", case.name, "--strict", "--accept", "needed today"]) == 0

    assert "because needed today" in capsys.readouterr().out
    assert (case / "overrides.json").exists()
    assert main(["validate", case.name, "--strict"]) == 0
    capsys.readouterr()
    assert main(["list"]) == 0
    assert "decision-accepted" in capsys.readouterr().out


@pytest.mark.parametrize("flag", [["--pinned"], ["--accept", "x"]])
def test_rigour_flags_need_strict(repo_root, monkeypatch, capsys, flag) -> None:
    monkeypatch.chdir(repo_root)
    case_path = _init(repo_root, "flags")

    assert main(["validate", case_path.name, *flag]) == 1
    assert "need --strict" in capsys.readouterr().err


def _consumer_with_field(repo_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(repo_root)
    with (repo_root / "pyproject.toml").open("a", encoding="utf-8") as handle:
        handle.write('\n[tool.fact-finder]\nrequired_brief_fields = ["Owner"]\n')


def test_a_consumers_required_field_is_scaffolded_and_blocks(
    repo_root: Path, monkeypatch, capsys
) -> None:
    _consumer_with_field(repo_root, monkeypatch)
    case_path = _init(repo_root, "owned", "--local-only", "--question", "Why?")
    report = case_path / "report.md"
    report.write_text(
        report.read_text(encoding="utf-8").replace(
            "<!-- research:placeholder -->",
            "Failures rose from 100 to 412 after the deploy, and the deploy explains it.",
            1,
        ),
        encoding="utf-8",
    )
    brief = case_path / "brief.md"
    assert "## Owner" in brief.read_text(encoding="utf-8")
    capsys.readouterr()

    assert main(["validate", case_path.name, "--strict"]) == 1
    assert "brief.md:" in capsys.readouterr().out

    brief.write_text(
        brief.read_text(encoding="utf-8").replace("<!-- research:placeholder -->", "Adam"),
        encoding="utf-8",
    )
    assert main(["validate", case_path.name, "--strict"]) == 0


def test_a_malformed_required_field_setting_is_a_clean_error(
    repo_root: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(repo_root)
    with (repo_root / "pyproject.toml").open("a", encoding="utf-8") as handle:
        handle.write('\n[tool.fact-finder]\nrequired_brief_fields = "Owner"\n')

    assert main(["init", "x", "--local-only"]) == 1

    assert 'Fix: write required_brief_fields = ["Owner"]' in capsys.readouterr().err


def test_a_new_entry_in_the_required_fields_tuple_is_scaffolded(
    repo_root: Path, monkeypatch
) -> None:
    monkeypatch.chdir(repo_root)
    fields = ("Question", "Owner")
    monkeypatch.setattr(templates, "REQUIRED_BRIEF_FIELDS", fields)
    monkeypatch.setattr(research, "REQUIRED_BRIEF_FIELDS", fields, raising=False)

    case_path = _init(repo_root, "tuple", "--local-only", "--question", "Why?")

    brief = (case_path / "brief.md").read_text(encoding="utf-8")
    assert brief.count("## Owner") == 1
    assert brief.count("## Question") == 1


@pytest.mark.parametrize(
    ("setting", "fix"),
    [
        ("sources_dir = 3", "sources_dir is not a string"),
        ('required_brief_fields = [""]', "required_brief_fields is not a list"),
        ('required_brief_fields = ["  "]', "required_brief_fields is not a list"),
        ("gsc_site = 3", "gsc_site is not a string"),
    ],
)
def test_a_bad_setting_names_its_key_and_fix(
    repo_root: Path, monkeypatch, capsys, setting: str, fix: str
) -> None:
    monkeypatch.chdir(repo_root)
    with (repo_root / "pyproject.toml").open("a", encoding="utf-8") as handle:
        handle.write(f"\n[tool.fact-finder]\n{setting}\n")
    command = (
        [
            "gsc",
            "--start-date",
            "2026-01-01",
            "--end-date",
            "2026-01-02",
            "--dimensions",
            "query",
        ]
        if setting.startswith("gsc_site")
        else ["source", "list"]
        if setting.startswith("sources_dir")
        else ["init", "x", "--local-only"]
    )

    assert main(command) == 1

    err = capsys.readouterr().err
    assert fix in err
    assert "pyproject.toml" in err
    assert "Fix:" in err


def test_from_spec_adds_a_consumers_required_field_and_keeps_a_supplied_one(
    repo_root: Path, monkeypatch
) -> None:
    monkeypatch.chdir(repo_root)
    with (repo_root / "pyproject.toml").open("a", encoding="utf-8") as handle:
        handle.write('\n[tool.fact-finder]\nrequired_brief_fields = ["Owner", "Budget"]\n')
    spec = repo_root / "spec"
    spec.mkdir()
    (spec / "brief.md").write_text(
        "# Research Brief\n\n## Question\n\nWhy?\n\n## Budget\n\nTen hours.\n",
        encoding="utf-8",
    )

    case_path = _init(repo_root, "spec-fields", "--from-spec", str(spec), "--local-only")

    brief = (case_path / "brief.md").read_text(encoding="utf-8")
    assert brief.count("## Owner") == 1
    assert "<!-- research:placeholder -->" in brief.split("## Owner", 1)[1]
    assert brief.count("## Budget") == 1
    assert "Ten hours." in brief
