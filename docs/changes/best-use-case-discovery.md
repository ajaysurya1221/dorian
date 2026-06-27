# Change note — best-use-case discovery (2026-06-27)

Adds the evidence-backed use-case package:
[`BEST_USE_CASE_2026_06_27.md`](../BEST_USE_CASE_2026_06_27.md),
[`USE_CASE_DECISION_MATRIX_2026_06_27.md`](../USE_CASE_DECISION_MATRIX_2026_06_27.md),
[`DEMO_SCRIPT_BEST_USE_CASE.md`](../DEMO_SCRIPT_BEST_USE_CASE.md),
[`CLAUDE_CODE_DORIAN_WORKFLOW.md`](../CLAUDE_CODE_DORIAN_WORKFLOW.md), and
[`POSITIONING_2026_06_27.md`](../POSITIONING_2026_06_27.md). The chosen wedge: **receipts for the
checkable claims an AI coding agent makes — especially the no-failing-test facts (config, signatures,
constants, references) — that REVOKE on drift**. No code, grammar, or security-posture change.

Dogfooded: the load-bearing facts the docs and demo rely on are sealed in
[`best-use-case-discovery.claims.json`](best-use-case-discovery.claims.json) under
`--strength-gate=fail` — the package is v1.2.0 with a zero-dependency core, the CLI exposes the
`revalidate` command the demo uses, and `SECURITY_BOUNDARY.md` states the not-a-sandbox boundary the
positioning leans on.
