# Investigation spec method

## Frame

Reason before any tool call. Classify the shape:

- `root-cause`: why did X happen?
- `comparison`: how does A differ from B?
- `exploration`: what is the state of X?

If the user pointed at a folder, pass it with `--context-path`. If they excluded a source, record
it. Every enabled source otherwise stays on, because a source that looks irrelevant at planning
time sometimes cracks the case later.

Decompose the target the way it is produced. This surfaces upstream sources that share no keywords
with the metric name:

- **Decomposition**: a rate splits into numerator and denominator, a funnel into stages, revenue
  into volume, price, and mix, and latency into queue and service time.
- **Upstream inputs**: what feeds each component, one or two levels up.
- **Downstream effects**: what the target feeds, to scope what is out.
- **Search terms**: search every upstream and downstream concept, not only the metric name.

## Discover

The usable set is the enabled bundles, web search, and `--context-path` folders. If the causal
chain needs a source that is not enabled, say so and suggest `research source enable <name>`. Do
not design around a hole. Discover in parallel where you can:

- **Warehouse and metrics**: discover objects live and confirm grain and definitions. The semantic
  layer is a convenience, not a boundary.
- **Experiments and flags**: scan the window for rollouts. This is the most common hidden cause of
  a metric shift, and even a null experiment rules a surface out.
- **Docs, chat, and issues**: search for retros, decisions, incidents, and what shipped.
- **Local context**: read it first. It is usually curated and high-signal.

A warehouse copy of Search Console or GA4 beats the live API, unless you need fresher data or an
API-only dimension. Size the sweep to the shape: a narrow lookup needs one or two sources.

Print a short summary: what the target means, which sources are confirmed, recent changes, known
confounders, and any important source that is off.

## Design

Hold several rival explanations at once and design tests that exclude them.

Write 3 to 5 ranked hypotheses, or angles for exploration and comparison. Good ones are:

- **Competing**: together they partition the explanation space. Include a measurement or freshness
  hypothesis, because instrumentation is a real cause.
- **Falsifiable**: each has a discriminating test whose result points to it or its rival, and an
  observation that would make you drop it.
- **Ranked**: most plausible first. Mark weak ones speculative.

Write research threads, 4 to 8 for root-cause and 1 to 3 for a narrow lookup:

- **Anchor first**: T1 confirms the event with hard numbers before anything explains it.
- **Order by information gain**: sharpest discriminating test first, not easiest.
- **Declare dependencies**: if T3 only makes sense after T1, say so.
- **Name objects**: `warehouse (signups_daily)`, not "the warehouse".
- **Flag speculation**: name the signal to abandon a thread.

Success criteria are specific ("top 2 or 3 drivers ranked with quantified contribution"), never
generic ("a clear answer").

Present the hypotheses, threads, scope, shape, and sources on and off. Wait for edits.

## Scaffold

`research init` writes the brief and the plan for the shape, including the exact headings and
fields validation reads. It generates `## Source Constraints` and `## Allowed Source Families` from
the source flags, so do not edit those two. Fill the rest with your design. `brief.md` becomes
binding once the goal starts.
