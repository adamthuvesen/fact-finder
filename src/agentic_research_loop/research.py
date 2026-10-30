from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .evidence import evidence_template
from .feedback import problem
from .from_spec import load_from_spec_dir, replace_markdown_section
from .io import extract_section, read_text, write_text
from .layout import (
    brief_path,
    case_dir,
    case_slug,
    evidence_path,
    notes_path,
    plan_path,
    queries_path,
    report_path,
    research_dir,
    source_objects_path,
)
from .sources import LOCAL_FAMILY, load_registry, source_constraints
from .templates import (
    NO_SOURCE_FAMILIES,
    RESEARCH_SHAPE,
    RIGOUR,
    brief_template,
    goal_prompt,
    notes_template,
    plan_template,
    queries_template,
    report_template,
    required_brief_fields,
    source_objects_template,
    with_required_sections,
)

DEFAULT_SUCCESS_CRITERIA = (
    "The answer directly addresses the question.",
    "Material claims have traceable evidence.",
    "Competing explanations are tested or left as explicit open risks.",
    "Calculated contributions reconcile to the relevant total when applicable.",
)


@dataclass(frozen=True)
class ResearchInitResult:
    case_id: str
    path: Path


def _brief_text(
    supplied_brief: str | None,
    *,
    question: str,
    template: str,
    constraints: list[str],
    families: list[str],
    rigour: str,
    required_fields: tuple[str, ...],
) -> str:
    if supplied_brief is None:
        return brief_template(
            question=question,
            template=template,
            source_constraints=constraints,
            allowed_families=families,
            success_criteria=list(DEFAULT_SUCCESS_CRITERIA),
            rigour=rigour,
            required_fields=required_fields,
        )
    brief = supplied_brief
    if RESEARCH_SHAPE.search(brief) is None:
        scope = extract_section(brief, "Scope")
        shape_line = f"- Research shape: `{template}`"
        brief = replace_markdown_section(
            brief, "Scope", f"{scope}\n{shape_line}" if scope else shape_line
        )
    if RIGOUR.search(brief) is None:
        scope = extract_section(brief, "Scope") or ""
        brief = replace_markdown_section(
            brief, "Scope", f"{scope}\n- Rigour: `{rigour}`".strip()
        )
    if extract_section(brief, "Question") is None:
        brief = replace_markdown_section(brief, "Question", question)
    brief = replace_markdown_section(
        brief,
        "Source Constraints",
        "\n".join(f"- {line}" for line in constraints if line.strip())
        + "\n\nAll external systems are read-only.",
    )
    brief = replace_markdown_section(
        brief, "Allowed Source Families", ", ".join(families) or NO_SOURCE_FAMILIES
    )
    return with_required_sections(brief, required_fields)


def create_manual(
    repo_root: Path,
    slug: str,
    *,
    template: str,
    question: str | None = None,
    sources: list[str] | None = None,
    source_hints: dict[str, str] | None = None,
    local_context_paths: list[str] | None = None,
    from_spec_path: Path | None = None,
    rigour: str = "exploratory",
) -> ResearchInitResult:
    """Create a case atomically: write a temp directory, then rename it into place.

    `sources` of None allows every registered source. A failed write leaves nothing.
    """
    case_id = case_slug(slug)
    path = case_dir(repo_root, case_id)
    parent = research_dir(repo_root)
    if parent.resolve() != repo_root.resolve() / parent.name:
        raise ValueError(
            problem(
                "research/ resolves outside the repository",
                "make research/ a plain directory inside the repo",
            )
        )
    if path.exists():
        raise FileExistsError(
            problem(
                "this case already exists",
                f"run `research next {case_id}`, or choose another slug",
                file=str(path),
            )
        )

    registry = load_registry(repo_root)
    names = list(registry) if sources is None else sources
    constraints = source_constraints(
        registry, names, hints=source_hints, local_context_paths=local_context_paths
    )
    families = [*names, *([LOCAL_FAMILY] if local_context_paths else [])]
    supplied = load_from_spec_dir(from_spec_path) if from_spec_path is not None else {}
    brief = _brief_text(
        supplied.get("brief"),
        question=question or f"Research: {slug}",
        template=template,
        constraints=constraints,
        families=families,
        rigour=rigour,
        required_fields=required_brief_fields(repo_root),
    )
    case_question = extract_section(brief, "Question") or question or slug

    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=parent, prefix=f".{case_id}."))
    try:
        write_text(brief_path(staging), brief)
        if rigour == "decision":
            write_text(evidence_path(staging), evidence_template(families))
        write_text(notes_path(staging), supplied.get("notes") or notes_template())
        write_text(
            report_path(staging),
            supplied.get("report")
            or report_template(template, case_question, rigour=rigour),
        )
        write_text(queries_path(staging), supplied.get("queries") or queries_template())
        write_text(
            source_objects_path(staging),
            supplied.get("source_objects") or source_objects_template(),
        )
        write_text(
            plan_path(staging), supplied.get("plan") or plan_template(template=template)
        )
        staging.chmod(0o755)
        staging.rename(path)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return ResearchInitResult(case_id=case_id, path=path.resolve())


def case_paths(repo_root: Path) -> list[Path]:
    """Return every case directory, skipping hidden staging directories."""
    parent = research_dir(repo_root)
    if not parent.is_dir():
        return []
    return sorted(
        path
        for path in parent.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )


def _resolve_existing_case_path(candidate: Path, expected_parent: Path) -> Path | None:
    if not candidate.exists():
        return None
    resolved = candidate.resolve()
    if not resolved.is_dir() or resolved.parent != expected_parent:
        raise FileNotFoundError(
            problem(
                f"{resolved} is outside the research directory {expected_parent}",
                "pass a case from `research list`",
            )
        )
    return resolved


def _suffix_case_match(repo_root: Path, value: str) -> Path | None:
    matches = [
        path for path in case_paths(repo_root) if path.name.endswith(f"-{value}")
    ]
    if len(matches) > 1:
        names = ", ".join(path.name for path in matches)
        raise FileNotFoundError(
            problem(f"case slug '{value}' matches {names}", "pass the full case id")
        )
    return matches[0] if matches else None


def resolve_case_path(repo_root: Path, value: str) -> Path:
    """Resolve a case identifier to its directory path within research_dir.

    Accepts a path, a full case ID, or a date-stripped suffix. Raises
    FileNotFoundError if the case is missing or resolves outside research_dir.
    """
    if not value:
        raise FileNotFoundError(
            problem("the case id is empty", "pass a case from `research list`")
        )
    expected_parent = research_dir(repo_root).resolve()
    resolved = _resolve_existing_case_path(
        Path(value), expected_parent
    ) or _resolve_existing_case_path(case_dir(repo_root, value), expected_parent)
    if resolved is not None:
        return resolved
    resolved = _suffix_case_match(repo_root, value)
    if resolved is not None:
        return resolved
    raise FileNotFoundError(
        problem(f"no case {value}", "pass a case from `research list`")
    )


def render_goal(case_path: Path) -> str:
    """Render the `/goal` contract, scoped to the sources this case may use.

    Only the bullet list is a source. Both brief writers close the section with a
    read-only reminder in prose, and the contract states that rule itself — left
    in, that sentence reads as another allowed source.
    """
    brief = read_text(brief_path(case_path))
    constraints = extract_section(brief, "Source Constraints") or ""
    sources = [
        stripped.removeprefix("-").strip()
        for line in constraints.splitlines()
        if (stripped := line.strip()).startswith("-")
        and stripped.removeprefix("-").strip()
    ]
    match = RIGOUR.search(brief)
    rigour = match.group(1).lower() if match else "decision"
    return goal_prompt(
        case_path, sources or ["No sources recorded in brief.md."], rigour=rigour
    )
