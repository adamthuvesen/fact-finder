# Demo case: export reliability

A complete root-cause case over the synthetic data in
[`../local-sources/`](../local-sources/). Read it to see the artifact shape a
finished investigation leaves behind before running one yourself.

Start with [`report.md`](report.md) for the answer. Then read
[`evidence.json`](evidence.json) for the checked claims and
[`review.json`](review.json) for the independent challenge.

Reproduce it:

```bash
uv run research init export-reliability --template root-cause \
  --question "Why did the weekly batch-export success rate drop in March 2026?" \
  --local-only --context-path examples/local-sources

uv run research goal <slug>
```

Paste the printed `/goal` block into Claude Code or Codex from the repo root. The
data is committed and synthetic, so this needs no API keys, no MCP servers, and
no network beyond the client you are already signed in to.

This is a decision case, so it carries the full evidence contract. A quick question needs
far less: `research init` scaffolds an exploratory case, and `report.md` is the only file it
must complete.

The figures here are derivable from `exports_weekly.csv` — a real run should land
on the same numbers. `evals/native-goal/rubric.md` scores exactly that, which is
why the canary workspace excludes this directory.
