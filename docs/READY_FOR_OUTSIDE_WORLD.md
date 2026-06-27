# Dorian — Ready for the Outside World? (v1.2.0)

> The release-readiness verdict for v1.2.0, with evidence. Follows the honesty contract in
> [`VALIDATION_HONESTY.md`](VALIDATION_HONESTY.md). Supersedes the v1.1.1-era
> [`PRODUCTION_READINESS_AUDIT.md`](PRODUCTION_READINESS_AUDIT.md) for release purposes.

## Verdict

**BLOCKED BY EXTERNAL CONSTRAINT — release-candidate-ready.**

Dorian v1.2.0 is, by every check that can be performed without account-owner action, ready for outside
users **within its stated trusted-repo scope**: the full test suite is green (local + CI ×3 Python
versions), the package builds and installs zero-dependency in a clean isolated environment, the
new-user golden path and `dorian init` work from that clean install, real external-repo trials pass,
and two independent reviews (Codex + an adversarial security-audit workflow) found **zero release
blockers** — every real finding is fixed-with-tests or honestly disclosed. The **one** thing standing
between this and a truthful "READY" is **public availability**: the canonical `pip install dorian-vwp`
still serves **1.1.1**, because publishing 1.2.0 to PyPI requires a one-time **PyPI Trusted Publisher**
configuration and a protected-environment deployment that **only the repository/PyPI account owner can
perform** (see [Release path](#release-path)). That is an external credential/approval gate, not a code
or quality gap — so the honest verdict is BLOCKED, not READY.

| field | value |
|---|---|
| Date | 2026-06-27 |
| Release version | 1.2.0 (tagged `v1.2.0`; GitHub release prepared) |
| `main` base | merged from `release/v1.2.0` |
| Public install (today) | `pip install dorian-vwp` → **1.1.1** (PyPI); 1.2.0 installable from the GitHub release wheel / `git+…@v1.2.0` |
| Scope | trusted internal repos; **not** a sandbox, not an LLM judge |

## Test & CI evidence

| Gate | Result |
|---|---|
| `ruff check` / `ruff format --check src tests bench` | PASS (125 files) |
| Full suite (`pytest`, local) | **948 passed** (944 + 4 new C5 regressions), EXIT 0 |
| Full suite in CI (`uv run pytest`) ×3.11/3.12/3.13 on `main` | PASS |
| `uv build` → sdist + wheel | PASS |
| Isolated wheel install (`dorian 1.2.0`, `uv pip check`) | PASS — **only `dorian-vwp` installed** (zero runtime deps) |
| Golden path from clean install + `dorian init` | PASS (drift → REVOKED, exit 4) |
| Benchmark suites re-run at 1.2.0 | reproduce exactly (binding-lifecycle same `run_id 168b50d9aa631d52`) |

## Independent review

- **Codex (read-only, fresh context)** — 5 findings. **Fixed with regression tests:** C5 `freshness:`
  string-comparison false-PASS, C5 shell `expect: regex:` ReDoS, C5 shell `expect: eq:` unbounded
  output, plus stale release metadata. **Disclosed + tracked:** F1 (`--checker-source base`
  selection/read-set residual). Corroborated the non-finding: **no** deny-exec/deny-shell → PASS bypass.
- **Adversarial security-audit workflow (8 dimensions, 18 agents)** — 5 real findings, **0 release
  blockers**; fixed the C5 sqlite `mode=ro` URI and the fixed-`.tmp` sealing race. Confirmed fail-closed
  invariants hold (blocked executable checkers ERROR, never PASS).
- **Final independent judge (fresh context)** — see [Judge verdict](#judge-verdict).

## Outside-world validation

5/5 trials PASS on a clean wheel install — real repos **python-dotenv** (`751f8c1…`) and **tomli**
(`5a77b12…`), a C4 pytest behavior trial, the `dorian init` golden path, and a first-hand trial on the
actual **1.2.0 wheel** (C4 behavior sealed under `--strength-gate=fail`); every deliberate drift
produced WARRANTED → **REVOKED** (exit 4). Full detail and honest limits in
[`OUTSIDE_WORLD_VALIDATION.md`](OUTSIDE_WORLD_VALIDATION.md).

## Security / trust boundary

- Single execution gate (`policy.py`); `deny-exec`/`deny-shell` **fail closed** (ERROR, never PASS) —
  independently confirmed by both reviews.
- C4 keeps the PATH-interpreter contract (`["python","-m","pytest",…]`); missing tooling → ERROR.
- Warrants are content-addressed (tamper → IntegrityError); regex checkers are ReDoS-bounded (now C5
  shell too); paths are repo-contained; sidecar writes are atomic (now per-process).
- **Honest residual:** `--checker-source base` substitutes only the checker *spec*; claim selection and
  read-set still come from the PR-head sidecar, so a *hostile fork* can suppress a re-check or forge a
  C1/`snapshot:` read-set. Disclosed in [`SECURITY_BOUNDARY.md`](SECURITY_BOUNDARY.md); base-ref
  selection is tracked hardening in [`NEXT_ALGORITHMIC_BETS.md`](NEXT_ALGORITHMIC_BETS.md). Moot for the
  trusted-repo product; for untrusted forks the doc requires `.warrant`-diff review + branch protection.

## Release path

The publish automation is sound but **owner-gated**:
- `publish.yml` — manual `workflow_dispatch`, builds from the tag, verifies tag == pyproject version,
  publishes to **PyPI via OIDC Trusted Publishing** through the protected GitHub Environment `pypi`.
- **Blocker:** PyPI Trusted Publishing requires a one-time Trusted-Publisher entry for project
  `dorian-vwp` → repo `ajaysurya1221/dorian` → workflow `publish.yml` → environment `pypi`, created on
  pypi.org by the account owner. It cannot be created from CI or by this session. The `testpypi`
  environment does not exist, so even the dry-run rehearsal cannot run here.
- **One action to unblock:** the owner confirms/creates that Trusted Publisher, then runs the `publish`
  workflow against tag `v1.2.0`. After it publishes, install from PyPI in a clean env and re-run the
  golden path to flip this verdict to READY.

## What READY would mean — and what it does not

**Would mean:** an outside user can `pip install dorian-vwp`, get 1.2.0, and run the verified golden
path on a trusted repo. **Does not mean:** safe for untrusted/public-fork checker execution (it is not
a sandbox), broad/market validation (one documented real catch; the rest is synthetic/scoped), or
semantic correctness beyond what the deterministic checkers verify.

## Remaining risks

| Risk | Severity | Status |
|---|---|---|
| PyPI serves 1.1.1 until owner publishes 1.2.0 | — | **the blocker** (external) |
| `--checker-source base` hostile-fork residual (F1) | Medium (out of trusted-repo scope) | disclosed + tracked |
| Evidence is mostly synthetic + 1 real catch | Low | stated plainly, not overclaimed |

## Judge verdict

An independent, fresh-context release judge (read-only, instructed to look for reasons *not* to ship)
returned **`BLOCKED BY EXTERNAL CONSTRAINT`**, with **no code/quality blockers**:

> "The release is genuinely ready on every axis that engineering can control — fixes are real and
> fail-closed, honesty is best-in-class, version story is enforced by a passing test — and the **only**
> thing standing between it and READY is an owner-only PyPI Trusted-Publisher action."

- **Fix verification:** all five fixed findings confirmed real and correct (the judge independently
  reproduced the freshness false-PASS and the sqlite URI injection).
- **Honesty:** PASS on every doc reviewed (README, SECURITY_BOUNDARY, DORIAN_USEFULNESS,
  OUTSIDE_WORLD_VALIDATION, BENCHMARK_CURRENT) — no sandbox/fork-safety/LLM-judge/market overclaim;
  trigger-vs-truth preserved.
- **F1:** agreed with disclose-and-defer for the trusted-repo scope (rushing a rewrite of the
  security-critical revalidation selection path would be riskier than the disclosed residual).
- **One nit it raised was fixed in response:** `freshness:` on mixed timezone-aware/naive dates now
  returns an explicit ERROR (it was already caught as ERROR by the harness; now it is explicit, with a
  test). The other nits (untracked snapshot files containing stale `1.1.1`; this placeholder) are
  cosmetic/operational and non-blocking.

Full transcript recorded in `.claude/ready_world_judge_verdicts.jsonl`.
