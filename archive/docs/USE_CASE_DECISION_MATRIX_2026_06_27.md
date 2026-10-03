# Use-Case Decision Matrix — 27 June 2026

> All eight candidate wedges, scored against the rubric by independent strategist agents (fed the
> 37-source research digest + competitive matrix), then adversarially critiqued. Companion to
> [`BEST_USE_CASE_2026_06_27.md`](BEST_USE_CASE_2026_06_27.md).

## Rubric & weights

Each dimension scored 1–5. For `overclaiming_risk` and `implementation_gap`, higher = worse.

```
weighted = 2.0*pain + 1.5*dorian_fit + 1.5*demo_clarity + 1.2*adoption_friction_inverse
         + 1.2*evidence_strength + 1.0*differentiation + 1.0*frequency + 0.8*urgency
         + 0.8*trust_boundary_fit + 0.5*expansion_potential
         - 1.5*overclaiming_risk - 1.0*implementation_gap
```

## Scores (ranked)

| Wedge | W | pain | fit | demo | friction⁻¹ | evid | diff | freq | urg | trust | exp | over‑claim | gap | verdict |
|---|--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|---|
| **A. AI-agent change-note verifier** | **63.7** | 5 | 5 | 5 | 4 | 5 | 5 | 5 | 4 | 4 | 5 | 3 | 1 | **PRIMARY** |
| E. Docs-drift detector | 59.7 | 4 | 5 | 5 | 3 | 4 | 4 | 4 | 3 | 5 | 4 | 2 | 2 | → fold into A (supporting) |
| B. PR-summary rot detector | 52.7 | 5 | 5 | 5 | 3 | 5 | 5 | 4 | 4 | 4 | 4 | 3 | 2 | **SECONDARY** |
| D. Platform-team AI governance | 42.7 | 5 | 5 | 3 | 2 | 4 | 5 | 4 | 4 | 5 | 5 | 3 | 4 | expansion (later) |
| C. Release-note truth gate | 42.5 | 3 | 5 | 5 | 4 | 3 | 4 | 2 | 3 | 5 | 4 | 2 | 1 | niche-but-clean |
| F. Compliance/provenance sidecar | 28.4 | 2 | 3 | 2 | 2 | 2 | 4 | 2 | 2 | 4 | 3 | 4 | 4 | **REJECT** |
| G. ML/data benchmark verifier | 23.3 | 3 | 3 | 3 | 2 | 1 | 3 | 2 | 2 | 2 | 3 | 4 | 4 | **REJECT** |
| H. OSS untrusted-contribution tool | 22.1 | 4 | 2 | 3 | 1 | 4 | 3 | 3 | 3 | 1 | 2 | 5 | 4 | **REJECT** |

## Synthesis

**Primary: A — refined.** Highest on pain, fit, demo, evidence, differentiation, frequency, and lowest
implementation gap (1). The adversarial critique kept it but **narrowed the framing**: a real agent
summary is *dominated* by behavioral/"tests cover X" claims, so do **not** pitch "verify the whole
summary." The defensible, differentiated core is the **no-failing-test facts** (config, packaging,
signatures, constants, file/symbol references) that **CI stays green on** when they drift — exactly the
gap tests/SAST/coverage cannot close. Adopt A with that honest scope.

**Secondary: B (PR-summary rot)** — same mechanism, team/maintainer framing; critique: re-scope from
"summary rot" to "load-bearing config/packaging/signature facts an agent asserts," because Dorian
re-checks only the *checkable* subset, not the prose.

**Fold in: E (docs-drift)** — scored #2 but the critique **downgraded it to a supporting case** because
"docs-drift detector" overclaims the mechanism: Dorian does **not** read docs and discover assertions;
a human/agent writes the claims. It is the *same* receipt mechanism pointed at a doc. Keep it as a
sub-use of A, not a separate headline.

**Expansion (not now): D (platform governance)** — strong pain/fit but demo=3, friction⁻¹=2, gap=4: a
top-down rollout, not a wedge. It is where A *expands* after bottom-up adoption.

**Clean niche: C (release-note truth gate)** — low frequency (releases are rare) but very clean demo
and trust fit; a good secondary marketing artifact, not the beachhead.

## Rejections (with reasons)

- **F. Compliance/provenance sidecar (28.4)** — wrong buyer (enterprise platform/security teams running
  attestation pipelines, not the local power user); trust-boundary mismatch; high overclaim/gap.
  in-toto/SLSA already own *build* provenance; Dorian's `export --in-toto` is experimental. **Complement,
  don't position here.**
- **G. ML/data benchmark verifier (23.3)** — branding it a "metric verifier" overclaims model-quality
  adjudication Dorian cannot do; metric claims reduce to a `confidence`-free threshold check. Weakest
  evidence (1). The C5 *schema/rowcount/freshness* capability is real but a feature, not the wedge.
- **H. OSS untrusted-contribution tool (22.1)** — **trust-boundary inversion**: the value prop asks the
  maintainer to trust a warrant produced by an *untrusted* contributor, violating Dorian's trusted-repo
  model (and `.warrant` files are unsigned/forgeable). Highest overclaim risk (5). Dorian helps the
  maintainer's **own** agent-assisted work, not untrusted fork PRs.

## The one-line test

A wins because it is the only wedge where all of these are simultaneously true: the pain is **named and
growing** (agent summaries go stale; "phantom changes"), Dorian's mechanism is an **exact fit**
(persist a specific claim → re-check on drift, token-free), the **demo lands in 3 minutes**, adoption is
**one `claims.json` + a GitHub Action**, and the differentiation answer ("why not tests/SAST/LLM-bot?")
is **clean** — *nothing else re-checks a specific stated fact after later drift, deterministically and
for free.*
