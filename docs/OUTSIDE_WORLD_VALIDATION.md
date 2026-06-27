# Outside-World Validation

> Evidence that an **outside user** can install dorian from a built wheel into a **clean isolated
> environment** and use it on **real external public repositories** — not just on dorian's own repo.
> Every drift below is a **deliberate validation mutation**, labeled as such, not an organic catch.
> Date: 2026-06-27. The durable committed evidence is the trials table below; a machine-readable
> `bench/public/results/outside_world_2026-06-27.json` plus raw per-trial logs are generated during the
> run (git-ignored, like every `bench/**/results` JSON — only this report is committed).

## Method

- **Artifact under test:** the built wheel an outside user installs (`dorian_vwp` wheel from the
  v1.2.0 release commit). Installed into fresh, isolated `uv venv`s (no system site-packages) via
  `uv pip install <wheel> pytest`.
- **Dependency footprint:** dorian itself pulled in **zero** runtime dependencies — the only other
  packages present were pytest's own deps (iniconfig, packaging, pluggy, pygments, pytest). Consistent
  with the token-free, empty-core-deps promise. (`pip check` / `uv pip check`: all compatible.)
- **Safety:** real repos were shallow-cloned at a **pinned commit SHA**; no external project test
  suite and no C5 `shell:` checker was executed; every mutation was reverted.
- **Version note:** Trials 1–4 were run with a wheel reporting `1.1.1` (built from the release commit
  *before* the `1.1.1→1.2.0` version-string bump); the verification code paths are identical. The
  actual **`1.2.0` wheel** was then independently exercised first-hand (Trial 5 below): clean isolated
  install → `dorian 1.2.0` (zero deps, `pip check` clean) → a C4 `pytest:` **behavior** claim sealed
  under `--strength-gate=fail` (exit 0) → break the behavior → `revalidate` → **BROKEN (`test_failing`)
  → REVOKED, exit 4**. So the release artifact itself is confirmed, not just the code.

## Trials

| # | Type | Repo @ pinned SHA | Claim → checker | Mutation | Trust transition | Exit | Result |
|---|------|-------------------|-----------------|----------|------------------|------|--------|
| 1 | Static / config metadata + drift | **python-dotenv** `751f8c148222e58aa173c83c4e5e6cfccb2cc124` (real, shallow) | `config-value:` on `requires-python` (value read from source first) | change the watched value | WARRANTED → **REVOKED** (`config_value_mismatch`) | 4 | **PASS** |
| 2 | Behavior, C4 pytest + drift | scratch repo (self-authored `calc.py` + test) | `pytest:test_calc.py::…` (C4) | break `calc.py` so the test fails | WARRANTED → **REVOKED** (`test_failing`) | 4 | **PASS** |
| 3 | New-user `dorian init` golden path | scratch repo (clean install) | scaffolded starter (`config-value:`/`path:`) | break the watched source | WARRANTED → **REVOKED** (`ref_missing`) | 4 | **PASS** |
| 4 | Static, second real repo (breadth) | **tomli** `5a77b12a7a9f052ce5a20c335d2825658f6aea52` (real, shallow) | `symbol:` on a real function | rename the symbol | WARRANTED → **REVOKED** (`symbol_missing`) | 4 | **PASS** |
| 5 | **v1.2.0 wheel**, C4 behavior + drift | scratch repo, clean `1.2.0` wheel install | `pytest:` (C4), sealed under `--strength-gate=fail` | break the implementation | WARRANTED → **REVOKED** (`test_failing`) | 4 | **PASS** |

Every trial: authored claims that were **true at the pinned SHA** (values read from source first),
sealed green (`verify` exit 0, sidecar written, `status` → WARRANTED), broke exactly one watched claim,
committed, ran `revalidate --since HEAD~1` → claim **BROKEN** + warrant **REVOKED** + **exit 4**, then
restored. Trial 3 ran the exact command `dorian init` scaffolds and it worked verbatim; the generated
GitHub Action is least-privilege (`contents: read`) and uses `fail_on: revoked`.

**Exit-code contract confirmed:** `0` on seal, **`4` on REVOKED**. (Caveat the validator caught: piping
dorian through `tee` masks its exit code — that is a shell gotcha, not a dorian bug; the GitHub Action
reads exit codes directly.)

## Friction an outside user would hit (honest)

1. **C4 needs bare `python` on PATH.** dorian runs `["python","-m","pytest",<nodeid>]` via the PATH
   interpreter (the intentional, documented contract). On macOS, which ships only `python3`, a C4 user
   must run inside a venv (which provides `python`) or prepend the venv's `bin` to PATH — otherwise C4
   correctly `ERROR`s (never a false pass/fail). By design, but a real first-run snag for C4 claims.
2. **Malformed config fixtures emit warning noise.** A repo that ships intentionally-broken TOML test
   fixtures (e.g. tomli) produces non-fatal `config file … could not be parsed` warnings while the
   binding index is built. Correct and non-blocking (those files are simply not indexed; the seal still
   completes), but visible stderr noise.

## What this proves — and what it does not

**Proves:** an outside user can `pip install` the wheel into a clean environment (zero runtime deps)
and run the full **seal → drift → REVOKED (exit 4)** lifecycle against real public repos, with the
correct trust transitions and exit codes, including a C4 behavior claim and the `dorian init` golden
path.

**Does not prove:** in-the-wild *organic* regression discovery (each drift here was a deliberate
mutation), nor that results transfer to any specific codebase, nor anything about C5 `shell:` (not
exercised), nor broad/market validation. Trials 2–3 use validator-authored scratch repos (needed for a
safe C4 test and a clean `init` target); Trials 1 and 4 are real external repos at pinned SHAs. Per
[`VALIDATION_HONESTY.md`](VALIDATION_HONESTY.md), this is **mechanism evidence on real install +
real repos**, not a claim that dorian is "validated in production."
