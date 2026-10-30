# Research Notes

## Working Theory

- Current best explanation: The 2026-03-09 scheduler change moved heavy export jobs into business hours, overloading the shared queue and cutting success rate.
- Confidence: medium. The timing is exact, but there is no control and one data file.
- What would change this: a non-scheduler change in the same window, or a metric-definition shift.

## Hypotheses

### H1: An operational change degraded export reliability
- **Status:** leading, not identified (one series, no control)
- **Why plausible:** The break lands on a single week rather than drifting.
- **Strongest rival:** Gradual load growth with no discrete cause.
- **Discriminating test:** Locate the break week, then check the operational notes for the same date.
- **Evidence so far:** The break is the week of 2026-03-09, the same date as the recorded scheduler change.
- **Next check:** None. Confirmed by a second signal (queue minutes).

### H2: Volume growth outran capacity
- **Status:** rejected for job count; job mix stays open
- **Why plausible:** More jobs on fixed capacity would raise queueing and timeouts.
- **Strongest rival:** Volume is flat and cannot account for the magnitude.
- **Discriminating test:** Compare the percentage change in scheduled jobs with the change in failure rate.
- **Evidence so far:** Scheduled jobs per week +2.0% against failures per week +716% (100 to 816). Job counts do not measure job size or mix, so a load change stays open.
- **Next check:** None.

### H3: Counting logic changed
- **Status:** rejected
- **Why plausible:** An apparent reliability break is sometimes a measurement break.
- **Strongest rival:** The notes explicitly rule it out.
- **Discriminating test:** Check that successes plus failures still equal scheduled jobs across the break.
- **Evidence so far:** Both windows reconcile exactly.
- **Next check:** None.

## Dead Ends

- Growth in job count: rejected, scheduled jobs per week rose 2%.
- Random variance: the step change aligns to the schedule change and holds for five post weeks.
- February retry-policy tweak: predates the inflection by two weeks; success rate held at 98% until the schedule change.

## Open Questions

- Did job size or mix change at the break? Job counts cannot say.
- Which tenants or job classes absorbed the failures? The weekly aggregate cannot say.
- Does the queue recover as the new schedule settles, or is the loss persistent?
