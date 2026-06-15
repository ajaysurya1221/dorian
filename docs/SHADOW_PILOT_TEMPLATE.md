# Shadow-mode pilot template

A structure for trying dorian on real work **without** letting it gate anything —
so you can measure whether it earns trust before you give it any. "Shadow mode"
means: dorian runs, records verdicts, and you compare them against reality, but a
dorian verdict never blocks a merge during the pilot.

This is a template to copy per pilot, not a record of a pilot that happened.

## Why shadow mode

A verification tool has to earn the right to block. Run it in shadow first to
learn its real false-positive rate and its real catch rate on *your* changes,
then decide whether to promote it to a gate. Gating a tool you have not measured
is how teams end up routing around a noisy check.

## Setup

- **Repo / team:** <name>; <how many people authoring AI changes>
- **Duration:** <e.g. 2 weeks / 20 PRs> (pre-commit to an end date)
- **Scope:** which artifacts get claims (e.g. PR descriptions for `src/api/**`)
- **Mode:** warn-only. In CI, set the Action `fail_on: never` so dorian reports
  but never fails the check. Locally, run `dorian revalidate` and read it; do not
  wire it into a pre-commit *block*.
- **Trust posture:** internal/trusted repo, or `--deny-exec` if any claims come
  from a less-trusted source. Never a public-fork gate during a pilot.

## What to record (per PR)

Use the [REAL_CATCH_LOG.md](REAL_CATCH_LOG.md) entry block for anything dorian
flags. Additionally, per PR, track:

| Field | Value |
|---|---|
| PR | <#> |
| Claims sealed | <n> |
| Claims re-checked this PR | <n> |
| dorian verdict | <ok / degraded / revoked> |
| Was a flagged break real? | <yes / no / n/a> |
| Was a real break missed? | <yes / no> |
| Author review time added | <minutes> |
| Did the author keep using it? | <yes / no> |

## Success / stop criteria (decide up front)

Pre-commit to thresholds so the result can't be rationalized after the fact:

- **Promote to gate if:** ≥1 real catch you would have shipped, AND false-alarm
  rate low enough that authors did not route around it (your number, set now).
- **Keep in shadow / iterate if:** triggers fire but the checker can't confirm
  (trigger-vs-truth gap) — tighten checkers, re-pilot.
- **Stop if:** no real catch and a false-alarm rate that cost more review time
  than it saved, by the end date.

## Honesty rules

- Log false alarms and misses with the same diligence as catches.
- A weak-binding warning is not a catch; record it as a warning.
- Do not promote to a gate on the strength of synthetic benchmarks alone — the
  pilot is the evidence that matters here.

## Outcome

- **Decision:** <promote / iterate / stop>
- **Numbers that drove it:** <catches, false alarms, misses, time>
- **What you'd change next pilot:** <…>
