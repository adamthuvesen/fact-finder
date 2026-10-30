# Research Report

## Question

Why did the weekly batch-export success rate drop in March 2026?

## Executive Summary

Export success rate stepped down from 98.0% to 84.0% in the week of 2026-03-09, the
same date a scheduler change moved **large warehouse export jobs** from overnight into
business hours. Failures rose from 100 to 816 per week, and average queue wait rose from
8 to 42 minutes in that week. [C1] [C5] [C3] The scheduler change is the leading
explanation, through queue contention. This case cannot prove it: the data is one weekly
series with no control group. [C4]

**Decision:** revert the schedule first, and treat queue isolation as a later test. This
data cannot compare the two options, and the reasons are under Decision. [C6]

## Ranked Causes

1. **Business-hours scheduling overloaded the export queue** (leading, not identified).
   The timing, the queue minutes, and the change log point here.
2. Change in job mix or size that job counts cannot show (open). Nothing in this data
   rules it out. No note records one.
3. Residual retry-policy noise (minor): the February tweak did not move the series.

## Evidence

Pre-change is the nine weeks from 2026-01-05 to 2026-03-02. Post-change is the five weeks
from 2026-03-09 to 2026-04-06. The windows differ in length, so counts are compared per
week.

| Measure | Pre | Post | Change |
| --- | ---: | ---: | ---: |
| Success rate (pooled) | 98.0% | 84.0% | -14.0 pp |
| Jobs failed per week | 100 | 816 | +716% |
| Jobs scheduled per week | 4,998.9 | 5,100 | +2.0% [C2] |
| Avg queue minutes | 8.0 | 42.0 | +425% |

The inflection week is the week of the documented scheduler change. `context/change-log.md`
records no change to success or failure counting logic in the window. Queue minutes and
failures come from one aggregate file, so they are not independent confirmation.

## Reconciliation

Successes and failures reconcile to scheduled jobs in both windows: pre-change
44,090 + 900 = 44,990; post-change 21,420 + 4,080 = 25,500. Rates are pooled over each
window, not averaged across weeks.

## Decision

The brief asks whether to revert the business-hours schedule or add queue isolation.

- **Revert:** the 98% rate was observed under the overnight schedule, so this returns to a
  known state. That is not proof of recovery, because nothing else was held fixed. The
  change log says the move aligned jobs with on-call coverage. A revert loses that benefit,
  and this data does not measure it.
- **Queue isolation:** this data says nothing about it. It holds no measure of an isolated
  queue, its capacity, or its effect on interactive load. It stays the better option only if
  on-call coverage matters more than a short delay. Test it on a subset of heavy jobs first.

Revert first because it is reversible and is the only option with any observed baseline.
Decide on isolation after that test. [C6]

## Rejected Leads

- **Growth in job count**: rejected. Scheduled jobs per week rose about 2% against an 8.16×
  rise in failures. This does not rule out a change in job size or mix, because job counts do
  not measure load.
- **Random variance**: rejected. All nine pre-change weeks show exactly 100 failures, and all
  five post-change weeks show 813 to 819.
- **Metric definition change**: rejected, on the change log's statement. The columns reconcile
  on both sides of the break.
- **February retry-policy tweak**: rejected as the main driver. It predates the break by two
  full weekly rows, and failures stayed at 100 per week until the break.

## Risks And Caveats

- This is one series with no control group or holdout. Timing and mechanism support the
  explanation. They do not identify a causal effect.
- The window ends at 2026-04-06, so the post-change period is five weeks. A longer window could
  show partial recovery as the queue settles.
- All counts come from one weekly aggregate file. There is no per-job or per-tenant cut to show
  which workloads absorbed the failures.
- Queue minutes are a weekly mean, so a within-week peak could carry more of the effect.
- The change log is an operational note, not an audited configuration diff.

## Recommended Next Actions

- Move large warehouse exports back to the overnight window, and monitor failures and queue
  minutes against the pre-change baseline.
- Before the reliability review, get a per-job cut to test the job-mix explanation.
- Trial queue isolation on a subset of heavy jobs, and measure the on-call cost of a revert.
