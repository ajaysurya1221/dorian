# Dorian — Production-Readiness Audit

> A point-in-time, evidence-backed readiness review. Every claim below was checked live against
> the repo, the test suite, the built package, and GitHub. Where a check could not be run, that is
> stated explicitly. This document follows the honesty contract in
> [`VALIDATION_HONESTY.md`](VALIDATION_HONESTY.md): no result is cited as proof of something it did
> not test.

## 1. Snapshot

| | |
|---|---|
| Audit date | 2026-06-27 |
| Package | `dorian-vwp` 1.1.1 (PyPI) |
| Default branch | `main` @ `b63c4db` (after merging PR #18, the `--strength-gate` feature) |
| Python support | `>=3.11`; CI matrix 3.11 / 3.12 / 3.13 |
| Core runtime deps | **0** (verified by isolated wheel install — only `dorian-vwp` is pulled in) |
| Optional extras | `[data]` → duckdb (parquet C5); `[extract]` → anthropic (claim **drafting** only, frozen/experimental — never on the verification path) |
| Audit environment | macOS 15 (darwin 25.5.0, aarch64), uv 0.11.24, CPython 3.12.13 in `.venv` |

### Release & PR state (verified via `gh`)
- Latest release tag: **v1.1.1**. 21 tags total (`v0.1.0` … `v1.1.1`).
- **PR #18** (`feature/strength-gate` → `main`): **MERGED** during this audit (was OPEN/MERGEABLE/CLEAN,
  all checks green). `main` advanced `6838e62` → `b63c4db`.
- `[Unreleased]` in `CHANGELOG.md` now covers two default-compatible additions: **C4 import-aware
  dependency binding** (PR #17, merged) and the opt-in **truth-axis `--strength-gate`** (PR #18,
  merged). Neither changes the warrant schema, checker grammar, exit codes, fold policy, or default
  behavior.
- **Dependabot PRs #9–#13**: 5 GitHub-Action major version bumps, all with a green `ci` check —
  but see [§8 deferred work](#8-known-limitations--deferred-work): the green check does **not**
  exercise the release/publish workflows those bumps actually touch.

## 2. Verdict

**MOSTLY READY — with listed, well-understood risks.**

For its **stated scope — trusted, internal repositories where humans or AI agents make checkable
engineering claims — Dorian is ready to use today.** The verification core is deterministic,
token-free, zero-dependency, exhaustively tested (944 tests green locally and in CI across three
Python versions), cleanly packaged, and honestly documented. The exit-code contract, the
born-verifiable seal, and the drift→revalidate→fold lifecycle all behave exactly as specified
(verified first-hand in §5).

It is **not** "production-ready" in the sense of *"safe to point at arbitrary untrusted input"* —
and it does not claim to be. C4 `pytest:` and C5 `shell:` checkers execute code; Dorian is a
verifier for trusted repos, **not a sandbox** (see [§7](#7-security-posture)). The residual risks
below are about *scope and operational hygiene*, not core correctness.

## 3. Test matrix (run this session)

All commands run from the repo root. Local environment note: this machine's bare `python` is not on
`PATH` and the editable `.pth` is intermittently unresolved (an endpoint-security/uv interaction —
**not** a code defect; CI is green per-run). A faithful local run that matches normal dev/CI
conditions — and changes **no** code or semantics — is:

```bash
export PATH="$PWD/.venv/bin:$PATH"   # bare `python` resolves → honors the C4 PATH-interpreter contract
export PYTHONPATH="$PWD/src"          # dorian imports regardless of the flaky editable .pth
```

| Gate | Command | Result |
|------|---------|--------|
| Lint | `uv run ruff check src tests bench` | **PASS** — "All checks passed!" |
| Format | `uv run ruff format --check src tests bench` | **PASS** — 125 files already formatted |
| Fast tests | `python -m pytest -m "not slow"` | **PASS** — 853 passed, 91 deselected, 47.7s |
| Slow tests | `python -m pytest -m "slow"` | **PASS** — exit 0, 91 tests (real subprocess/git/wheel/bench) |
| Full suite | (fast + slow) | **944 tests, all green** |
| Full suite in CI | `uv run pytest` on 3.11/3.12/3.13 | **PASS** (authoritative; `gh pr checks`/`gh run list`) |
| CLI smoke | `python -m dorian --help` / `--version` | **PASS** |
| Packaging | `uv build` + isolated wheel install | **PASS** (see §6) |
| Golden path | full new-user lifecycle in a temp repo | **PASS** (see §5) |

## 4. CLI surface (smoke-checked)

`dorian --help` renders the full command surface: `init, capture, seal, verify, status, blast,
bindings, bind-suggest, rebind, revalidate, report, suggest-data-checks, suggest-claims, sync,
export, bench`. Global flags `--repo`, `--json`, `--version` work. Execution-policy flags
(`--deny-exec`, `--deny-shell`), the two opt-in review gates (`--binding-gate`, `--strength-gate`,
each `off|warn|fail`, default `off`), and `--allow-restricted` are present on the relevant
subcommands.

## 5. Golden-path transcript (first-hand, temp repo)

Mirrors the README "Try it in 30 seconds" recipe, then exercises the new strength gate. Exit codes
observed match the contract (`0` ok, `4` revoked/seal-refused):

```
# verify a born-verifiable warrant
$ dorian verify note.md --claims claims.json
verified 1/1 claim(s) against current sources -> note.md.warrant      exit 0
$ dorian status
WARRANTED note.md  sha256:aed57cfb…  VERIFIED=1                        exit 0

# a refactor renames the symbol the note claims exists; note.md is untouched
$ dorian revalidate --since HEAD~1
BROKEN  handler-exists  C3: symbol_missing
fold    WARRANTED -> REVOKED                                          exit 4
$ dorian status
REVOKED note.md  BROKEN=1                                             exit 4

# strength gate (truth axis) on a load-bearing `behavior` claim backed only by an existence check
$ dorian verify note.md --claims claims.json                          # default off → seals  exit 0
$ dorian verify … --strength-gate=warn                                # seals + prints diagnostic  exit 0
    adequacy_mismatch: 'behavior' claim backed only by existence — only a C4 pytest checker proves behavior
$ dorian verify … --strength-gate=fail                                # refuses, no sidecar  exit 4
    weak checker: claim 'login-behavior' (kind=behavior, backed only by existence)
    --strength-gate=fail refused seal: … no sidecar written
```

The `--strength-gate=fail` refusal is **atomic no-write** — no `.warrant` is left behind. Confirmed
on disk.

## 6. Packaging

- `uv build` produces `dorian_vwp-1.1.1-py3-none-any.whl` (~136 KB) and
  `dorian_vwp-1.1.1.tar.gz` (~3.4 MB sdist) with no warnings.
- **Isolated install smoke test** (fresh venv, install the built wheel only):
  `python -m dorian --version` → `dorian 1.1.1`; the `dorian` console script works; **only
  `dorian-vwp` is installed** — confirming the zero-runtime-dependency promise end-to-end.
- The sdist is large (~3.4 MB) because it ships docs, tests, and benchmark fixtures. This is
  harmless but worth noting as a future trim opportunity; the **wheel** users actually install is
  lean. (Low priority — see punch list.)

## 7. Security posture

A full file:line security map was produced this session; headline findings (all consistent with
[`SECURITY_BOUNDARY.md`](SECURITY_BOUNDARY.md)):

- **Single execution gate.** `policy.py`'s `ExecutionPolicy` is the one place C4/C5 execution is
  gated. Blocked execution **fails closed**: it returns `Verdict.ERROR`, and the protocol already
  refuses to seal on ERROR (`ERRORED_AT_SEAL`) and folds to UNKNOWN on revalidate — never a silent
  PASS. `--deny-exec` blocks both C4 and C5; `--deny-shell` blocks C5 shell only.
- **C4 PATH-interpreter contract intact.** C4 runs `["python", "-m", "pytest", <nodeid>]` via the
  PATH interpreter (list-args, no shell). Missing `python`/`pytest` yields ERROR, never a false
  pass/fail. (This audit deliberately did **not** change this to `sys.executable`.)
- **C5 shell uses `shell=True`** by design — claims/warrants are *executable input*. There is no
  caller-side string interpolation (the command is the spec verbatim), so there is no injection
  surface *Dorian introduces*; the trust requirement is that you trust the claim author. Mitigations:
  `--deny-shell`, `--deny-exec`, `checker_trust: base` / `--checker-source base` (run base-ref specs
  on PRs, never a fork's added checkers), and external sandboxing.
- **C3 regex is ReDoS-bounded**: pattern length capped (500 chars), compiled in a spawned worker
  process with a hard wall-clock timeout that escalates to SIGKILL; a catastrophic-backtracking
  pattern yields ERROR (`regex_timeout`), never a stall or pass.
- **Warrant integrity is content-addressed.** The warrant id is `sha256(canonical_json(body))`;
  `Warrant.load()` recomputes and raises `IntegrityError` on any tamper. Maps to exit 4.
- **Path containment** is enforced uniformly: every checker resolves paths and rejects anything not
  `is_relative_to(repo)`. The optional `[tool.dorian.scopes]` lint refuses to seal a claim that
  *names* a restricted path (exit 6) unless `--allow-restricted` — a naming policy, **not** a runtime
  sandbox (documented).
- **Atomic writes**: sidecars are written to `*.tmp` then `os.replace`d in the same directory.
- **Least-privilege CI**: workflows declare `permissions: contents: read`; `persist-credentials:
  false`; actions are pinned by commit SHA.

**Three things a security reviewer should still verify independently:** (1) the env-var fallbacks
`DORIAN_DENY_EXEC/SHELL` only honor `1/true/yes/on` — a typo silently *enables* execution, so CI must
use the explicit flag, not env-only; (2) scope lint is name-based, not execution containment — do not
rely on it for confidentiality of executed reads/writes; (3) sidecar trust rests on filesystem + git
integrity plus the content-address check — confirm no integration path skips `Warrant.load()`.

## 8. Known limitations & deferred work

- **Dependabot #9–#13 are deferred, not merged.** They bump `checkout` (in `publish.yml` only —
  every other workflow is already on v6.0.3), `upload-artifact`, `download-artifact`, `cache`, and
  `attest-build-provenance`. Every one of these except the `publish.yml` checkout lives **only** in
  the release / publish / micro-benchmark workflows, which the green `ci` job does **not** run. So
  their passing check is not evidence the bump is safe. These are *major* version jumps into the
  release/attestation path of a published package. **Recommended verification path:** dry-run the
  artifact bumps through `publish-testpypi.yml`, and validate `attest-build-provenance@v4` on a
  release candidate, before merging. Not done here because cutting a release is out of the authorized
  scope of this audit.
- **The trigger-vs-truth ceiling is real and intended.** A claim can be perfectly *triggered*
  (re-checked when the right file changes) yet carry no *truth* signal stronger than its checker.
  `symbol:` proves a name exists, not that behavior is correct — only a C4 `pytest:` checker proves
  behavior. `--strength-gate` now surfaces/refuses the worst of these mismatches, but it is opt-in
  and advisory; it never marks a claim false.
- **Claim extraction is frozen/experimental.** `--extract` (LLM claim *drafting*) failed its
  metamorphic calibration gate twice and is not a recommended path. Agents should emit `claims.json`
  directly (see [`AGENT_CLAIMS.md`](AGENT_CLAIMS.md)); `suggest-claims`/`suggest-data-checks` produce
  deterministic scaffolds. None of this touches the verification path.
- **`export --in-toto` is experimental** interop, explicitly labeled.
- **sdist size** ~3.4 MB (docs/tests/fixtures shipped) — cosmetic, low priority.

## 9. Punch list (ranked by severity × leverage)

| # | Item | Severity | Leverage | Action |
|---|------|----------|----------|--------|
| 1 | Dependabot release-path bumps unverified by CI | Medium | Medium | Verify via TestPyPI + RC, then merge or close (§8) |
| 2 | README flagship demo mis-kinded a `reference` claim as `behavior` | Low | High | **Fixed this session** (kind → `reference`; test synced) |
| 3 | No single "is it ready?" doc for new users | Low | High | **Fixed this session** (this audit + `DORIAN_USEFULNESS.md`) |
| 4 | `--extract` frozen status not bold enough in onboarding prose | Low | Medium | Add a one-line callout in `USE_WITH_CLAUDE_CODE.md` |
| 5 | sdist ships tests/fixtures (~3.4 MB) | Low | Low | Optional Hatch `exclude` trim |
| 6 | Local editable-install flakiness (this machine) | Low | Low | Environment-only; recipe documented in §3 |

## 10. Bottom line

Dorian does the rare thing of holding *itself* to its own standard: its headline demo, its release
process, and its claims about its own evidence are all checkable, and most are checked in CI. The
core is correct, deterministic, token-free, and well-tested. Adopt it for trusted internal repos with
AI coding agents today; treat the release-path dependency bumps and the executable-checker trust
boundary as the two things to handle deliberately rather than on autopilot.
