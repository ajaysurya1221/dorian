# Release gate — dorian 1.0.0

The 1.0.0 promotion decision is made by a **deterministic state machine**
(`bench/release_state.py`), not by ad-hoc human judgement. It reads only
machine-verifiable facts (version files, the git tag/commit relationship,
workflow files, doc text, claim status, benchmark result files) plus a recorded
`release_evidence.json` of gate outcomes, and emits exactly one decision:

```
PROMOTE_1_0_READY | CUT_RC2_READY | STAY_RC
HALT_UNSAFE | HALT_INSUFFICIENT_EVIDENCE | HALT_PUBLISH_NOT_CONFIGURED
HALT_VERSION_MISMATCH | HALT_NONDETERMINISTIC
```

It never runs pytest itself, never touches the network, never calls a model, and
never asks a question. Missing gate evidence under `--strict` is
`HALT_INSUFFICIENT_EVIDENCE`, not a fabricated pass.

## Run it

```bash
# record gate outcomes first (lint/tests/build/benchmark determinism), then:
uv run python bench/release_state.py \
  --target 1.0.0 \
  --json --strict \
  --out .release/current/release_state.json \
  --decision-out .release/current/RELEASE_DECISION_1_0.md

# or pin the current RC baseline explicitly:
uv run python bench/release_state.py \
  --target 1.0.0 \
  --rc-tag v1.0.0rc2 \
  --json --strict \
  --out .release/rc2-evidence/release_state.json \
  --decision-out .release/rc2-evidence/RELEASE_DECISION_1_0.md
```

Exit code: `0` for any GO decision (PROMOTE / CUT_RC2 / STAY_RC), non-zero for any
`HALT_*`. Commit-specific output should be written under `.release/<run>/`, not
committed as source truth.

## State table

| id | gate | blocker | fail → |
|---|---|---|---|
| S0 | repo clean or dirty only with expected release-branch files | yes | HALT_UNSAFE |
| S1 | pyproject / `__init__` / uv.lock agree; current RC tag exists and matches the target line | yes | HALT_VERSION_MISMATCH |
| S2 | Week-2 complete (config-value impl+doc, audit atomicity) | no | → STAY_RC |
| S3 | lint + format + tests + build + install smoke (from evidence) | yes | HALT_UNSAFE / HALT_INSUFFICIENT_EVIDENCE |
| S4 | public-repo harness exists, verifies cache, ERROR≠BROKEN | yes | HALT_UNSAFE |
| S5 | ≥1 repo with proof-backed machine-derived benchmark-ready claims | no | → STAY_RC |
| S6 | benchmark executed (≥2 repos), deterministic ×2, all known-truth matched | yes | HALT_NONDETERMINISTIC / HALT_INSUFFICIENT_EVIDENCE |
| S7 | benchmark docs honesty-guarded (no forbidden phrases, required framing) | yes | HALT_UNSAFE |
| S8 | no `pull_request_target`, ci permissions, log-injection test, dispatch-only microbench | yes | HALT_UNSAFE |
| S9 | provenance/attestation workflow exists | only under `--require-publish` | CUT_RC2 / HALT_PUBLISH_NOT_CONFIGURED |
| S10 | TestPyPI Trusted-Publisher dry-run workflow exists | only under `--require-publish` | CUT_RC2 / HALT_PUBLISH_NOT_CONFIGURED |

### Decision logic (S11)

1. Any blocker FAIL with a `HALT_*` wins, by priority: version → unsafe →
   nondeterministic → publish-not-configured → insufficient-evidence.
2. Otherwise, if there is no executed machine-derived benchmark evidence
   (S2/S5/S6 not all PASS) → **STAY_RC**.
3. Otherwise, if **new user-visible behavior landed after the current RC tag**
   (`features_after_rc`) or the provenance/publish path still needs a live
   workflow run → **CUT_RC2_READY**.
4. Otherwise → **PROMOTE_1_0_READY**.

## Signed-tag / provenance policy

A local interactive agent session does **not** hold the maintainer's signing key,
so this automation never fabricates a "signed" tag. The **provenance of record**
for a 1.0.0-line artifact is the **GitHub artifact attestation** produced by
`release-gate.yml` (`actions/attest-build-provenance`): an in-toto / SLSA
build-provenance statement signed via Sigstore and recorded in the public
transparency log, bound to the exact wheel/sdist by digest. This is the accepted
GA provenance lane.

A GPG/SSH-signed annotated git tag is **additive**, not a substitute: when the
maintainer cuts the real release tag they should sign it (`git tag -s`), but its
absence does not block the GA decision because attestations already establish
build provenance. Releasing without *either* attestations or a signed tag is not
permitted.

## Publish path is separate from the GitHub release gate

- `release-gate.yml` — build + 3.11/3.12/3.13 test matrix + sha256 + **attest
  provenance**. Manual dispatch or pushed tag; never a fork PR. No PyPI upload.
- `publish-testpypi.yml` — **TestPyPI** dry-run via Trusted Publishing (OIDC,
  `id-token: write`, environment `testpypi`, no stored token). Rehearses the wiring.
- `publish.yml` — real **PyPI** publish via Trusted Publishing (OIDC, environment
  `pypi`). Manual dispatch against a tag only.

None of these are triggered by this automation. Promotion to a public release is a
deliberate maintainer action after the state machine returns a GO decision.
