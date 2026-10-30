from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from .layout import local_today

# A scaffolded section carries this token until someone replaces it. Validation
# looks for the token, not for template wording, so real prose cannot trip it.
PLACEHOLDER = "<!-- research:placeholder -->"
NO_SOURCE_FAMILIES = "none"
EXPLORATORY_LABEL = "Exploratory answer: not independently reviewed."
RIGOUR = re.compile(
    r"(?im)^[ \t]*-[ \t]*\*{0,2}Rigour\*{0,2}:\*{0,2}[ \t]*`?([A-Za-z-]+)`?"
)
# Tolerates the bold variants a hand-written brief uses, such as `- **Research shape:**`.
RESEARCH_SHAPE = re.compile(
    r"(?im)^[ \t]*-[ \t]*\*{0,2}Research shape\*{0,2}:\*{0,2}[ \t]*`?([A-Za-z-]+)`?"
)


def format_list(items: Iterable[str]) -> str:
    values = [item for item in items if item]
    return "\n".join(f"- {value}" for value in values) if values else "- (none)"


def root_cause_hypothesis_starters(question: str) -> str:
    metric_label = question.rstrip(" ?")
    return "\n".join(
        [
            "- **H1: A real behavior shift changed the metric in a concentrated segment or cohort.** [priority: high, status: untested]",
            f"  - Discriminating test: Break `{metric_label}` by segment, cohort, geography, or workflow step and confirm the shift survives at least one cross-source check.",
            "  - Strongest rival: The apparent movement is mostly composition drift, seasonality, or normal variance.",
            "  - Evidence needed: A concentrated change with a plausible mechanism, plus corroboration from a second source family or adjacent metric.",
            "  - Completion threshold: Done when the leading segment(s) and direction of effect are explicit, or blocked with the exact missing cut/data dependency named.",
            "- **H2: Upstream inputs or feeder cohorts changed before the observed metric moved.** [priority: high, status: untested]",
            f"  - Discriminating test: Check the upstream driver for `{metric_label}` one step earlier in the funnel or lifecycle and compare timing, magnitude, and affected slices.",
            "  - Strongest rival: The outcome changed without a matching upstream shift, which points to downstream execution or retention instead.",
            "  - Evidence needed: A lead/lag relationship or a clearly weaker feeder cohort that lines up with the downstream pattern.",
            "  - Completion threshold: Done when the upstream contribution is quantified or directionally clear enough to rank against other drivers, or ruled out as too small or mistimed.",
            "- **H3: Measurement, attribution, or freshness issues explain part of the movement.** [priority: medium, status: untested]",
            f"  - Discriminating test: Verify `{metric_label}` with an independent definition, source, or cutoff date and inspect known tracking, routing, or reporting changes near the inflection.",
            "  - Strongest rival: Multiple independent sources show the same movement, so the change is real even if measurement is noisy.",
            "  - Evidence needed: A concrete mismatch between sources/definitions or a confirmed instrumentation change that overlaps the observed shift.",
            "  - Completion threshold: Done when measurement risk is either ruled in as material or bounded tightly enough that the remaining explanation is still trustworthy.",
        ]
    )


def root_cause_cross_check_lines() -> str:
    return "\n".join(
        [
            "- Name the main freshness hazard before comparing live data with snapshots or local exports.",
            "- Cross-check every high-confidence claim in at least two source families when possible.",
            "- Record the strongest rival explanation for each major thread before calling it done.",
            "- If a surprising finding changes the case, preserve `brief.md` and log the pivot in `notes.md` plus the relevant thread status in `plan.md`.",
        ]
    )


def brief_template(
    *,
    question: str,
    template: str,
    source_constraints: list[str],
    allowed_families: list[str],
    success_criteria: list[str],
    rigour: str = "exploratory",
    today: date | None = None,
) -> str:
    today_text = (today or local_today()).isoformat()
    root_cause_sections = (
        f"""## Hypotheses

{root_cause_hypothesis_starters(question)}

## Known Confounders

- Which seasonality, composition, routing, or attribution effects could mimic the observed change?
- Which freshness caveats matter before you compare sources?

## Required Cross-Checks

{root_cause_cross_check_lines()}

"""
        if template == "root-cause"
        else ""
    )
    return f"""# Research Brief

## Question

{question}

## Deliverable

- Answer the question with evidence and make the conclusion usable by its intended reader.

## Scope

- In scope:
- Out of scope:
- Research shape: `{template}`
- Rigour: `{rigour}`
- Created: `{today_text}`

{root_cause_sections}## Source Constraints

{format_list(source_constraints)}

All external systems are read-only. Do not send messages, change experiments, update documents, or write to data stores.

## Allowed Source Families

{", ".join(allowed_families) or NO_SOURCE_FAMILIES}

## Definitions And Reconciliation

- Define the primary metric, population, time zone, and comparison window before drawing conclusions.
- State how the result reconciles to its source totals. If reconciliation does not apply, explain why.

## Freshness Requirements

- Which facts must be verified live?
- Which context can come from existing docs?

## Success Criteria

{format_list(success_criteria)}
"""


def plan_template(*, template: str) -> str:
    if template == "root-cause":
        return """# Research Plan

## Research Design Contract

- Every high-priority thread needs a main explanation, strongest rival, discriminating test, evidence target, and completion threshold.
- Completion thresholds should say what counts as `done`, when to mark a thread `blocked`, and what would justify a `pivoted` status.
- Record the biggest confounder or freshness hazard for each major thread and the source you will use to cross-check it.

## Thread Template

Use the exact bold field names below — they are machine-parsed by validation.

```md
### T<n>: <short title>
**Priority:** high / medium / low
**Source:** <which source family to use>
**Objective:** What specific question this thread answers
**Main Explanation:** <current best explanation under test>
**Strongest Rival:** <best competing explanation>
**Discriminating Test:** <the concrete check that would move confidence>
**Evidence Needed:** <what would count as enough evidence>
**Completion Threshold:** done when ... / blocked when ... / pivot when ...
**Confounders / Freshness Risks:** <what could mislead this thread>
**Cross-Check:** <which second source or method will validate the claim>
**Depends on:** none / T<n>
**Status:** pending
```

## Threads

No plan yet. Write the threads that materially help this investigation.
"""
    return """# Research Plan

No plan yet. Use this file only when sequencing or dependencies help the case.
"""


def notes_template() -> str:
    return """# Research Notes

## Working Theory

- Current best explanation:
- Confidence:
- What would change this:

## Hypotheses

Use this as a lightweight ledger, not a form to fill perfectly.

### H1: <short hypothesis>
- **Status:** active | supported | weakened | rejected | pivoted
- **Why plausible:**
- **Strongest rival:**
- **Discriminating test:**
- **Evidence so far:**
- **Next check:**

## Dead Ends

- None yet.

## Open Questions

- None yet.
"""


def report_template(
    template: str, question: str, *, rigour: str = "exploratory"
) -> str:
    middle_heading = {
        "root-cause": "Ranked Causes",
        "comparison": "Key Differences",
        "exploration": "Current Picture",
    }[template]
    label = f"{EXPLORATORY_LABEL}\n\n" if rigour == "exploratory" else ""
    return f"""# Research Report

{label}## Question

{question}

## Executive Summary

{PLACEHOLDER} Complete this section with the answer and the most decision-relevant evidence.

## {middle_heading}


## Evidence

{PLACEHOLDER} Say what supports the answer.

## Reconciliation

{PLACEHOLDER} Show how calculated contributions reconcile to the source total. If reconciliation does not apply, say so.

## Rejected Leads

{PLACEHOLDER}

## Risks And Caveats

{PLACEHOLDER}
"""


def queries_template() -> str:
    return """-- Preserve every SQL query used as evidence below.
-- Put `-- query_id: <id>` above a query that an evidence.json source cites.
-- If no SQL is used, replace this file with: -- No SQL used: <reason>
"""


def source_objects_template() -> str:
    return f"""# Source Objects

List one bullet per source object: its fully qualified name or stable URL, in backticks, then the access date.

{PLACEHOLDER}
- `<object name or URL>` (accessed YYYY-MM-DD)
"""


def goal_prompt(
    case_path: Path, source_constraints: list[str], *, rigour: str = "exploratory"
) -> str:
    """Render the native `/goal` contract for a case.

    Every path is absolute. A goal that is handed relative paths can write correct
    analysis into the wrong directory, which is exactly how a case looks complete while
    the real case directory sits untouched.
    """
    case_path = case_path.resolve()
    constraints = "\n".join(f"- {line}" for line in source_constraints if line.strip())
    opening = f"""/goal Complete the bounded research case at `{case_path}`.

Read `{case_path / "brief.md"}` first and treat its question, scope, source constraints, definitions, and success criteria as binding. Write only inside `{case_path}`. You may read repository instructions, skills, and any source the brief allows. Treat every external system as read-only. Never fabricate evidence.

This case may use only these sources:

{constraints}

Run `uv run research contract method` and follow it.
"""
    closing = f"""Run `uv run research validate "{case_path}" --strict`, fix every error, consider every warning, and surface the result and final conclusion in your last response. Validation checks integrity and arithmetic. It cannot prove semantic truth or reviewer independence. If a rigour check does not fit this case, tell the user; only a person may accept it with `--accept "<reason>"`. Stop early only if a concrete external dependency makes the case impossible to complete, and record that blocker in `report.md`."""
    if rigour == "exploratory":
        return f"""{opening}
This is an exploratory case: a quick, labelled answer. Keep the label line at the top of `report.md`. Write the answer and its caveats there. Keep every SQL query in `queries.sql`, and list what you used in `source-objects.md`. Say plainly when the evidence is thin. If the answer will drive a decision that matters, say so, and suggest re-running with `research init --rigour decision`.

{closing}"""
    return f"""{opening}Run `uv run research contract evidence` and follow it.

Maintain these artifacts as you work:
- `notes.md` for hypotheses, dead ends, and open questions
- `report.md` for the usable answer, reconciliation, rejected leads, and caveats, with a marker such as [C1] beside each material claim
- `queries.sql` for every SQL query used, or an explicit reason no SQL was used
- `source-objects.md` for every source object used
- `evidence.json` for sources, source coverage, material claims, and checked calculations (`uv run research schema evidence` prints the schema)
- preserved source excerpts or aggregate results inside the case, which `evidence.json` lists by SHA-256
- `plan.md` only when a separate plan materially helps the investigation

Every claim cites a declared source. Reconcile calculated contributions to the relevant source total when applicable. Do not count shared upstream data as independent corroboration. Continue until the report answers the question and every material claim is evidence-backed.

Before finishing, delegate the final challenge to an independent subagent that did not conduct the research. Give it the final artifacts and preserved evidence for read-only review. It must identify the strongest competing explanation, the weakest-supported material claim, the most fragile source or calculation, and any material objection. Do not replace the independent review with your own assessment. Record its name or task id and its findings in `review.json` (`uv run research schema review`), using `uv run research review-snapshot "{case_path}"` for `reviewed_hashes`. A snapshot only prints hashes and approves nothing. Never replace a hash without a new review. A review that predates small edits warns; a material change needs another review.

{closing}"""
