# fact-finder

A research kit for bounded investigations. A case records its question, evidence, and report, and validation checks that the evidence supports the answer.

## Core

**Case**:
One investigation, in its own directory `research/<case>/`.
_Avoid_: project, task

**Brief**:
A case's `brief.md`: the question, the scope, and the rigour line.

**Rigour**:
How much evidence a case owes, chosen when the case starts: `exploratory` or `decision`. A brief with no rigour line is a decision case.

**Evidence manifest**:
A case's `evidence.json`: its sources, coverage, claims, and calculations. A decision case needs one, and an exploratory case does not.

## Terms that collide with model-finder

**Source**:
One recorded piece of evidence in the evidence manifest, with its family, route, locator, access time, and artifact hash.
Not the same as in model-finder, where a source is a warehouse that a pull reads.

**Bundle**:
One `<name>.toml` file in the sources directory: a source's spec, its optional MCP server, and its connector write tools.
Not the same as in model-finder, where a bundle is a warehouse connector directory.

**Finding**:
One validation result, a `Finding` with a kind that decides whether it blocks, such as `safety` or `format`.
Not the same as in model-finder, where a finding is a free-text line in a review.

**Exploratory**:
The lighter rigour level, chosen before the work. It needs no evidence manifest or review, and its report carries the exploratory label.
Not the same as in model-finder, where exploratory is a label applied to a result after the fact.
