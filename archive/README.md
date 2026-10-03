# archive

Historical artifacts, kept for provenance and no longer part of the current story.

In June 2026 dorian was **re-aimed** from "documentation-staleness detector" to the
deterministic accountability layer for **AI-agent claims** — verifying that what an agent
*said it did* is true against the code, now and on every future change. The current docs
live in [`../docs/`](../docs/): start with [`AGENT_CLAIMS.md`](../docs/AGENT_CLAIMS.md)
(how an agent emits claims) and [`BENCHMARK_v0.7.0.md`](../docs/BENCHMARK_v0.7.0.md).

What's here:

- **`RELEASE_NOTES_v0.1.0.md` … `v0.7.1.md`** — the early per-version release notes (the
  pre-1.0 iteration history).
- **`CHURN_BENCHMARK_v0.3.0.md` / `v0.4.0.md` / `v0.5.0.md`**, **`EXTRACT_GATE_RESULTS.md`** —
  measurements of the LLM claim *extractor*, which is now **frozen** (the supported path is an
  agent emitting `claims.json` directly; see [`../docs/AGENT_CLAIMS.md`](../docs/AGENT_CLAIMS.md)).
- **`KILL_REPORT_TEMPLATE.md`**, **`KILL_REPORT_v0.0.md`**, **`RELEASE_VALIDATION_REPORT_v0.2.0.md`** —
  the early validation-discipline reports and template.
- **`docs/`** — dated planning, positioning, readiness-audit, and release-gate notes from the
  June 2026 re-aim and the 1.0–1.4 line (`POSITIONING_*`, `BEST_USE_CASE_*`,
  `READY_FOR_OUTSIDE_WORLD.md`, `PRODUCTION_READINESS_AUDIT.md`, `RELEASE_GATE_1_0.md`,
  `DORIAN_PANE.md`, …). Kept for history; they are not maintained and may describe the code as it
  was on their date, not as it is now. The live docs are in [`../docs/`](../docs/).

The extraction-gate *specifications* that present (frozen) bench code still treats as normative —
`EXTRACT_GATE.md` and `REAL_DOC_METAMORPHIC_GATE.md` — remain in [`../docs/`](../docs/) alongside
the benchmark summaries.
