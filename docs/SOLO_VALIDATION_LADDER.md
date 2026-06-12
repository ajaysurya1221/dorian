# Solo validation ladder

A full multi-repo public benchmark with independent reviewers is the right
*eventual* bar, but it is not feasible for a solo developer right now. This
ladder replaces it with evidence steps one person can actually run, each one
strictly harder to fake than the last. Climb in order; do not skip to claims
a lower rung has not earned.

## Level 0 — Selftest (exists)

The deterministic fixture benchmark already in `bench/`, run via `make bench`.
Proves the harness shape and the revalidation mechanics, not real-world
performance.

## Level 1 — Public micro-benchmark

Solo-feasible scope:

- 1–2 public repos, frozen SHAs;
- 2–4 artifacts total;
- 5–10 **manual** claims per artifact (no `--extract`);
- owner labels only, recorded next to the claims;
- every artifact, claim, warrant, label, and score is publishable.

Goal: **reproducibility, not final proof.** Anyone can re-run the harness on
the same SHAs and get the same alarms. This is the first rung that produces a
number someone else can check.

## Level 2 — Mutation benchmark

Apply controlled mutations to repos with warranted artifacts (rename a
symbol, change a default, delete a route, alter a schema field) and score
whether the right claims break — and *only* those.

- Tests binding coverage (does the support set actually watch what the claim
  depends on?) and checker brittleness (do string/regex checkers fire on
  cosmetic edits?).
- Fully deterministic; no external reviewers required.

## Level 3 — Private shadow pilot

Shadow-mode use on the private data-oriented AI backend. Rules:

- disposable local clone only;
- no writes to the private repo, no sidecars committed there, no pushes;
- results stay local; only aggregate notes (counts, ratios, minutes) leave.

Success metrics — pass requires the last one plus any of the first three:

- 5 high-value stale-claim catches; or
- 10× fewer false positives than file-change alarms; or
- review overhead under 10 minutes per artifact/update cycle; and
- **zero security exceptions.**

## What this ladder does not claim

Climbing all four rungs is still not the public-launch benchmark (multiple
repos, independent labels, published adjudication). It is the evidence needed
to justify *building* that benchmark — and to keep the public story honest
until it exists.
