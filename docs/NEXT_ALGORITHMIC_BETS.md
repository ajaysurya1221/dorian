# Next algorithmic bets

The five bets worth making next, ranked. Ground rules that bound all of
them: extraction remains **draft-only**; do not auto-seal arbitrary prose;
do not build dashboards, SaaS, or platform features.

## 1. Multi-index binding engine

- **Why it matters:** binding is the main correctness blocker. Today support
  sets come mostly from string mentions; a claim about a route or schema can
  silently miss the file that actually defines it, producing false
  confidence (the warrant verifies while the world drifted).
- **Smallest slice:** one extra index — Python symbol definitions (name →
  defining file via `ast`) — consulted at seal time to expand `watch` sets
  for claims that mention a known symbol.
- **Acceptance test:** a fixture claim mentioning `verify_token` gets the
  defining file added to its watch set even when the claim text never names
  the file; renaming that file is then caught by revalidation.
- **Not yet:** route/OpenAPI/dbt/lineage indices, cross-language support,
  embedding-based binding.

## 2. Weak-binding trust gate

- **Why it matters:** a weakly bound claim that seals as TRUSTED is worse
  than an unbacked one — it carries false confidence. `dorian bindings`
  already diagnoses weakness but never gates.
- **Smallest slice:** an opt-in seal flag that downgrades claims with
  existing diagnostics (unbacked, single-file, short-literal) to a
  review-required state instead of sealing them silently.
- **Acceptance test:** sealing a fixture with one short-literal-bound claim
  under the flag yields the downgraded state and a receipted event; without
  the flag, behavior is unchanged.
- **Not yet:** mandatory gating by default, scoring models, reviewer
  workflows.

## 3. Typed checkers

- **Why it matters:** string/regex checkers are brittle both ways — they
  break on cosmetic edits and survive semantic ones. Typed checkers (parse,
  then compare) cut both error classes.
- **Smallest slice:** one checker — Python symbol signature (function
  exists, arity/defaults match) via `ast`, no new dependencies.
- **Acceptance test:** fixture matrix — unchanged signature PASS, changed
  default FAIL, cosmetic reformat of the same function PASS (where the
  equivalent regex checker would FAIL).
- **Not yet:** OpenAPI/route/dbt/config-file checker families, a checker
  plugin system.

## 4. Mutation tests for warrants

- **Why it matters:** the only honest way to measure binding coverage and
  checker brittleness (Level 2 of `docs/SOLO_VALIDATION_LADDER.md`) is to
  mutate the repo and see whether the right claims — and only those —
  break.
- **Smallest slice:** a bench subcommand applying 3 canned mutation types
  (rename symbol, change literal default, delete file) to a fixture repo and
  scoring caught/missed/spurious per claim.
- **Acceptance test:** on the demo fixture, the report shows each mutation
  attributed to the expected claim with zero spurious breaks; output is
  deterministic across runs.
- **Not yet:** generative/LLM-driven mutations, mutation campaigns against
  external repos, CI integration.

## 5. Deterministic anchor-first extraction prototype

- **Why it matters:** measured churn keeps `--extract` failing its stability
  gate because the model re-*selects* claims each run. Anchoring first
  (segment the artifact, derive candidate spans deterministically, then ask
  the model only to classify/fill per anchor) attacks the variance at its
  source.
- **Smallest slice:** a prototype path that segments a markdown artifact
  into anchor spans deterministically and emits checkable/uncheckable
  buckets per span, with claim IDs canonicalized from anchor positions.
- **Acceptance test:** 3 re-runs on the committed demo doc produce identical
  anchor sets and claim IDs; churn measured by `dorian bench churn` drops
  below the existing 0.20 gate on that doc.
- **Not yet:** promotion of `--extract` out of experimental (that takes
  public churn *and* coverage gates), auto-seal of extracted output —
  extracted claims stay drafts for human review.

*Shipped in v0.4.0 (`--extract-mode anchor`) and measured against the v0.3.0
restate baseline with the same 7-agent protocol: exact churn 0.187 → 0.029
(gate 3/7 → 7/7 PASS; identical claim-text sets in 4/7 invocations, 15/21 run
pairs vs 3/21). The gate criterion is met; unconditional run-identity is not yet
(residual single-span selection jitter). See
[`CHURN_BENCHMARK_v0.4.0.md`](CHURN_BENCHMARK_v0.4.0.md). The "not yet" list
stands.*
