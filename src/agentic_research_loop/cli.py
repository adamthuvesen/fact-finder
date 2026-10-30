from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from .doctor import run_doctor
from .evidence import Evidence, Review, review_snapshot
from .google_api import GoogleApiError, GoogleAuthError, ga4_report, gsc_query
from .layout import find_repo_root, project_setting
from .repo_setup import setup_repo
from .research import case_paths, create_manual, render_goal, resolve_case_path
from .source_bundles import disable_bundle, enable_bundle, render_bundle_list
from .validation import GATE_LIMITS, Assessment, accept_findings, assess_case

CONTRACT_DIR = Path(__file__).parent / "contract"
CONTRACT_FILES = {"method": "method", "evidence": "evidence-contract"}
READ_FAILURES = (OSError, UnicodeError, ValueError, RecursionError)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _iso_date(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a valid YYYY-MM-DD date") from exc
    return value


def _comma_list(value: str) -> list[str]:
    values = [item.strip() for item in value.split(",")]
    if any(not item for item in values):
        raise argparse.ArgumentTypeError(
            "must be a comma-separated list with no blanks"
        )
    return values


def _source_hint(value: str) -> tuple[str, str]:
    name, separator, hint = value.partition("=")
    if not separator or not name.strip() or not hint.strip():
        raise argparse.ArgumentTypeError("must use SOURCE=TEXT")
    return name.strip(), hint.strip()


def _add_init_arguments(init_parser: argparse.ArgumentParser) -> None:
    init_parser.add_argument("slug", help="Short case slug")
    init_parser.add_argument("--question", help="Specific research question")
    init_parser.add_argument(
        "--template",
        choices=("exploration", "root-cause", "comparison"),
        default="exploration",
    )
    init_parser.add_argument(
        "--rigour",
        choices=("exploratory", "decision"),
        default="exploratory",
        help="exploratory: a labelled quick answer. decision: the full evidence contract.",
    )
    init_parser.add_argument(
        "--sources",
        type=_comma_list,
        help="Comma-separated sources this case may use. Default: every registered source.",
    )
    init_parser.add_argument(
        "--local-only",
        action="store_true",
        help="Allow no external source; investigate only --context-path files.",
    )
    init_parser.add_argument(
        "--source-hint",
        action="append",
        default=[],
        type=_source_hint,
        metavar="SOURCE=TEXT",
        help="Focus an allowed source. Can be passed more than once.",
    )
    init_parser.add_argument(
        "--context-path",
        action="append",
        default=[],
        help="Attach a local context folder or file. Can be passed more than once.",
    )
    init_parser.add_argument(
        "--from-spec",
        type=Path,
        help="Directory of pre-authored artifacts. The brief's source sections are always generated.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research",
        description="Prepare and validate research cases run with native agent goals",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_init_arguments(subparsers.add_parser("init", help="Create a case workspace"))

    goal_parser = subparsers.add_parser(
        "goal", help="Print the native /goal command for a case"
    )
    goal_parser.add_argument("case", help="Case id or path")

    validate_parser = subparsers.add_parser("validate", help="Validate a case")
    validate_parser.add_argument("case", help="Case id or path")
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Completion check at the case's rigour level.",
    )
    validate_parser.add_argument(
        "--pinned",
        action="store_true",
        help="With --strict, also block when any reviewed file changed since the review.",
    )
    validate_parser.add_argument(
        "--accept",
        metavar="REASON",
        help="With --strict, accept the rigour blocks for this reason. The override is recorded and labelled. Safety cannot be overridden.",
    )
    validate_parser.add_argument(
        "--json", action="store_true", help="Print the result as JSON."
    )

    subparsers.add_parser("list", help="List cases with their status")

    schema_parser = subparsers.add_parser(
        "schema", help="Print an evidence contract JSON schema"
    )
    schema_parser.add_argument("artifact", choices=("evidence", "review"))
    snapshot_parser = subparsers.add_parser(
        "review-snapshot", help="Print current artifact hashes. This approves nothing."
    )
    snapshot_parser.add_argument("case", help="Case id or path")

    contract_parser = subparsers.add_parser(
        "contract", help="Print the research method or the evidence contract"
    )
    contract_parser.add_argument("document", choices=tuple(CONTRACT_FILES))

    subparsers.add_parser(
        "setup",
        help="Write client MCP configs and deny lists for enabled bundles, and link skills",
    )
    subparsers.add_parser(
        "doctor",
        help="Check enabled servers against their read-only control. Checks config only.",
    )

    gsc_parser = subparsers.add_parser(
        "gsc", help="Query the Search Console API. Prefer a warehouse copy when synced."
    )
    gsc_parser.add_argument("--start-date", required=True, type=_iso_date)
    gsc_parser.add_argument("--end-date", required=True, type=_iso_date)
    gsc_parser.add_argument(
        "--dimensions",
        required=True,
        type=_comma_list,
        help="Comma-separated: query,page,country,device,searchAppearance,date",
    )
    gsc_parser.add_argument("--row-limit", type=_positive_int, default=100)
    gsc_parser.add_argument("--start-row", type=_non_negative_int, default=0)

    ga4_parser = subparsers.add_parser("ga4", help="Query the GA4 Data API")
    ga4_parser.add_argument("--start-date", required=True, type=_iso_date)
    ga4_parser.add_argument("--end-date", required=True, type=_iso_date)
    ga4_parser.add_argument("--dimensions", required=True, type=_comma_list)
    ga4_parser.add_argument("--metrics", required=True, type=_comma_list)
    ga4_parser.add_argument("--limit", type=_positive_int, default=25)
    ga4_parser.add_argument("--offset", type=_non_negative_int, default=0)
    ga4_parser.add_argument("--order-by", help="Metric name to sort descending")

    source_parser = subparsers.add_parser("source", help="Manage opt-in source bundles")
    source_sub = source_parser.add_subparsers(dest="source_command", required=True)
    enable_parser = source_sub.add_parser(
        "enable", help="Wire a bundle into config/sources.json and the client configs"
    )
    enable_parser.add_argument("name", help="Bundle name, e.g. github")
    disable_parser = source_sub.add_parser("disable", help="Remove a bundle's wiring")
    disable_parser.add_argument("name", help="Bundle name")
    source_sub.add_parser("list", help="List bundles and whether they are enabled")

    return parser


def _init_case(repo_root: Path, args: argparse.Namespace) -> int:
    if args.local_only and args.sources:
        raise ValueError("--local-only and --sources cannot be combined")
    result = create_manual(
        repo_root,
        args.slug,
        template=args.template,
        question=args.question,
        sources=[] if args.local_only else args.sources,
        source_hints=dict(args.source_hint),
        local_context_paths=args.context_path,
        from_spec_path=args.from_spec,
        rigour=args.rigour,
    )
    print(f"Created case: {result.case_id}")
    print(f"Path: {result.path}")
    print(f"Next: uv run research goal {result.case_id}")
    return 0


def _empty_assessment(error: str) -> Assessment:
    return Assessment(rigour="decision", strict=True, errors=[error], warnings=[])


def _assess(repo_root: Path, args: argparse.Namespace) -> tuple[str, Assessment]:
    """Validate a case, reporting any failure to read it as a validation error."""
    try:
        case_path = resolve_case_path(repo_root, args.case)
        if args.accept is not None:
            accept_findings(case_path, args.accept, pinned=args.pinned)
        return str(case_path), assess_case(
            case_path, strict_completion=args.strict, pinned=args.pinned
        )
    except READ_FAILURES as exc:
        return args.case, _empty_assessment(str(exc))


def _validate_command(repo_root: Path, args: argparse.Namespace) -> int:
    if (args.accept is not None or args.pinned) and not args.strict:
        raise ValueError("--accept and --pinned need --strict")
    case, result = _assess(repo_root, args)
    if args.json:
        print(
            json.dumps(
                {
                    "case": case,
                    "strict": args.strict,
                    "rigour": result.rigour,
                    "passed": not result.errors,
                    "errors": result.errors,
                    "warnings": result.warnings,
                    "accepted": result.accepted,
                    "label": result.label,
                    "limits": GATE_LIMITS,
                },
                indent=2,
            )
        )
        return 1 if result.errors else 0
    if result.errors:
        print("Validation failed:")
        for error in result.errors:
            print(f"- {error}")
    if args.strict:
        for warning in result.warnings:
            print(f"Warning: {warning}")
    elif result.warnings:
        print(f"{len(result.warnings)} items remain for --strict to report.")
    if result.errors:
        return 1
    print(f"Validation passed: {case}")
    if args.strict:
        print(result.label)
        print(GATE_LIMITS)
    return 0


def _case_status(case_path: Path) -> str:
    try:
        if assess_case(case_path).errors:
            return "invalid"
        result = assess_case(case_path, strict_completion=True)
    except READ_FAILURES:
        return "invalid"
    if result.errors:
        return "in-progress"
    if result.accepted:
        return f"{result.rigour}-accepted"
    if result.review_is_stale:
        return f"{result.rigour}-stale-review"
    return f"{result.rigour}-complete"


def _list_command(repo_root: Path, _args: argparse.Namespace) -> int:
    cases = case_paths(repo_root)
    if not cases:
        print("No cases yet. Create one with `research init <slug>`.")
        return 0
    width = max(len(path.name) for path in cases)
    for path in cases:
        print(f"{path.name:<{width}}  {_case_status(path)}")
    return 0


def _doctor_command(repo_root: Path, _args: argparse.Namespace) -> int:
    checks = run_doctor(repo_root)
    for check in checks:
        print(f"[{check.status.upper()}] {check.source}: {check.message}")
    if not checks:
        print("No sources enabled. Enable one with `research source enable <name>`.")
    print(
        "This checks local config against each declared read-only control. "
        "It does not contact or test the upstream server."
    )
    return 1 if any(check.status in {"fail", "needs-setup"} for check in checks) else 0


def _print_actions(actions: list[str]) -> int:
    for line in actions:
        print(f"- {line}")
    return 0


def _source_command(repo_root: Path, args: argparse.Namespace) -> int:
    if args.source_command == "list":
        print(render_bundle_list(repo_root))
        return 0
    action = enable_bundle if args.source_command == "enable" else disable_bundle
    return _print_actions(
        action(repo_root, args.name) or [f"'{args.name}' was not enabled"]
    )


def _required_setting(repo_root: Path, *, env: str, setting: str, example: str) -> str:
    value = os.environ.get(env) or project_setting(repo_root, setting)
    if not value:
        raise GoogleApiError(
            f"{env} is not set. Set it, or set {setting} under "
            f"[tool.agentic-research-loop] in pyproject.toml. Example: {example}"
        )
    return value


def _gsc_command(repo_root: Path, args: argparse.Namespace) -> int:
    if args.start_date > args.end_date:
        raise ValueError("--start-date must be on or before --end-date")
    result = gsc_query(
        site=_required_setting(
            repo_root,
            env="GSC_SITE",
            setting="gsc_site",
            example="https://www.example.com/",
        ),
        start_date=args.start_date,
        end_date=args.end_date,
        dimensions=args.dimensions,
        row_limit=args.row_limit,
        start_row=args.start_row,
    )
    print(json.dumps(result, indent=2))
    return 0


def _ga4_command(repo_root: Path, args: argparse.Namespace) -> int:
    if args.start_date > args.end_date:
        raise ValueError("--start-date must be on or before --end-date")
    result = ga4_report(
        property_id=_required_setting(
            repo_root,
            env="GA4_PROPERTY_ID",
            setting="ga4_property_id",
            example="123456789",
        ),
        start_date=args.start_date,
        end_date=args.end_date,
        dimensions=args.dimensions,
        metrics=args.metrics,
        limit=args.limit,
        offset=args.offset,
        order_by=args.order_by,
    )
    print(json.dumps(result, indent=2))
    return 0


def _goal_command(repo_root: Path, args: argparse.Namespace) -> int:
    print(render_goal(resolve_case_path(repo_root, args.case)))
    return 0


def _snapshot_command(repo_root: Path, args: argparse.Namespace) -> int:
    snapshot = review_snapshot(resolve_case_path(repo_root, args.case))
    print(json.dumps(snapshot, indent=2))
    return 0


def _contract_command(_repo_root: Path, args: argparse.Namespace) -> int:
    print(
        (CONTRACT_DIR / f"{CONTRACT_FILES[args.document]}.md").read_text(
            encoding="utf-8"
        )
    )
    return 0


def _setup_command(repo_root: Path, _args: argparse.Namespace) -> int:
    return _print_actions(setup_repo(repo_root) or ["nothing to do"])


COMMANDS = {
    "init": _init_case,
    "goal": _goal_command,
    "validate": _validate_command,
    "list": _list_command,
    "review-snapshot": _snapshot_command,
    "setup": _setup_command,
    "doctor": _doctor_command,
    "gsc": _gsc_command,
    "ga4": _ga4_command,
    "source": _source_command,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "contract":
            return _contract_command(Path(), args)
        if args.command == "schema":
            model = Evidence if args.artifact == "evidence" else Review
            print(json.dumps(model.model_json_schema(), indent=2))
            return 0
        return COMMANDS[args.command](find_repo_root(), args)
    except (GoogleApiError, GoogleAuthError, *READ_FAILURES) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
