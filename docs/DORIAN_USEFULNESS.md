# Dorian's Usefulness

> Why this project matters, written for engineers, maintainers, AI-agent users, and skeptical
> reviewers. Every evidence claim here is labeled by strength and traceable to a file in this repo.
> Nothing is cited as proof of something it did not test — the rule from
> [`VALIDATION_HONESTY.md`](VALIDATION_HONESTY.md).

## One-sentence thesis

Dorian is a **local-first, git-native, token-free verifier for AI-generated engineering claims**: a
human or agent writes checkable claims, Dorian proves them with deterministic checkers and seals each
into a `.warrant` sidecar, and it re-checks them automatically when the files they depend on later
drift — so a claim that was true when written cannot silently rot.

## The problem: verification debt

AI coding agents do not just write code — they write **assertions about** code. "I added retry logic
to `client.py`." "The timeout is now 30 seconds." "This is covered by `test_auth.py`." "I dropped
Python 3.8 support." Each assertion is a small promise. Today those promises are verified, if at all,
by a human reading a diff and a paragraph and deciding whether to believe them.

That creates **verification debt** — the growing gap between *claims made* and *claims actually
checked*:

- **It scales with output, not with review capacity.** An agent can produce more plausible-sounding
  claims per hour than any reviewer can independently confirm. The reviewer's realistic options are
  to trust, or to re-derive the check by hand. Most trust.
- **It is invisible once merged.** A claim that was true at merge time degrades silently as later,
  unrelated commits touch the same code. The PR description still reads perfectly. The portrait in the
  attic is the one that changed.
- **Tests and CI don't cover most of it.** Packaging metadata, config values, cross-file
  invariants, "X still calls Y", "the constant is still 30" — these rarely have a failing test, so
  green CI is not evidence the claim held.

Dorian's bet is that the durable unit worth keeping is not the prose summary but **the specific,
checkable claim plus the deterministic evidence for it plus the trigger that re-checks it later.**

## What Dorian uniquely preserves

When Dorian seals a warrant it persists three things that are normally thrown away the moment a PR
merges:

1. **The specific claim** — a structured statement with a `kind` (`fact`/`reference`/`behavior`/
   `quantity`/`decision`) and whether it is `load_bearing`.
2. **Its deterministic evidence** — the exact checker that proves it (a hashed span, a symbol/regex
   reference, a pinned config value, a pytest nodeid, a data assertion) and the read-set it was
   verified against, content-addressed so tampering is detectable.
3. **Its future re-check trigger** — the set of files whose drift should make this claim re-prove
   itself. Change one of those files and the claim re-runs its checker; the warrant folds to
   `TRUSTED`, `DEGRADED`, or `REVOKED` accordingly.

That third item is the part no diff, comment, or commit message keeps. It is what turns a one-time
assertion into a **standing, self-rechecking invariant**.

## What Dorian is good at

- **AI-agent claims after coding work.** An agent emits `claims.json` alongside its change; `dorian
  verify` refuses to seal if any claim is already false (born-verifiable). The claim survives as a
  warrant, not as unverified prose. See [`AGENT_CLAIMS.md`](AGENT_CLAIMS.md).
- **PR review support.** `dorian revalidate --since <base>` re-checks only the claims whose watched
  files intersect the PR's diff, and emits a customer-readable comment with a `Blocked/Passed/Errored`
  verdict and the exact claim that changed. Reviewers spend attention where a promise actually moved.
- **Documentation / change-note claims.** A change note that says "`handler()` lives in `app.py`" or
  "the retry ceiling is 5" becomes a checker, not a hope. When a later refactor breaks it, the
  warrant — not the reader — notices.
- **Config / quantity claims.** `config-value:` and `py-const:` pin a *typed* value (`30 ≠ 30.0 ≠
  "30"`). This catches the class of change that has no test and keeps CI green — the
  `requires-python` floor, a feature flag default, a schema column.
- **Behavior claims backed by tests.** A C4 `pytest:` checker runs the named test at seal and at
  every re-check; behavior is proven by execution, never by an LLM's opinion.
- **Drift detection over time.** The same deterministic checker re-runs on every later commit that
  touches a watched file. No re-inference, no tokens, same verdict every time.

## What Dorian is not

- **Not an LLM judge.** There is zero model-token spend on the verification path, by design and by
  constraint. Checkers are hashes, parses, greps, test runs, and data reads.
- **Not a SaaS dashboard.** It is a local CLI + a git sidecar + an optional GitHub Action. Nothing
  phones home; the warrant lives next to the file it backs.
- **Not a sandbox.** C4 `pytest:` and C5 `shell:` checkers execute code. Dorian is for **trusted,
  internal repositories**. `--deny-exec`/`--deny-shell`/`checker_trust: base` fail closed but are
  trust controls, not isolation. See [`SECURITY_BOUNDARY.md`](SECURITY_BOUNDARY.md).
- **Not a universal proof system.** It proves what its checkers can deterministically check on
  Python-centric repos and tabular/structured data — not arbitrary semantic correctness.
- **Not a replacement** for tests, SAST, code review, or human judgment. It is the layer that keeps
  *specific stated claims* honest as code drifts — a complement to all of those.

## Why token-free verification matters

The verification path is deterministic and model-free, and that is not an aesthetic choice:

- **Determinism.** The same claim against the same code yields the same verdict, forever. No
  temperature, no drift in the judge, no "it passed yesterday."
- **Inspectability.** A checker is `symbol:src/auth.py::login` or `pytest:tests/test_x.py::test_y`.
  You can read exactly what is being proven and why a verdict is what it is. There is no opaque score.
- **Repeatability & CI economics.** Re-checking on every PR costs CPU milliseconds, not tokens. A
  reviewer-bot that re-inferred claims with an LLM on every commit would be expensive, slow, and
  non-reproducible. Dorian's recheck is free and identical run-to-run.
- **Trust.** The thing deciding truth is code you can audit, pinned by content hash — not a vendor's
  model behind an API. That is a precondition for using it *as a gate* rather than as a suggestion.

## Honest evidence so far

Strength-labeled, with paths. Read these as "what specific false statement does this rule out," per
the project's own honesty rule.

**Real-world catch (strongest).**
[`REAL_CATCH_LOG.md`](REAL_CATCH_LOG.md) documents a real cross-PR catch on the public `encode/httpx`
repo: a `config-value:pyproject.toml:project.requires-python:">=3.8"` claim, against upstream PR #3592
("drop Python 3.8 support"), folded `WARRANTED → REVOKED` (exit 4). This is the highest-conviction
evidence — real code, a real change, independently reproduced on a frozen SHA, and a change with **no
failing test** (packaging metadata; CI stays green), which is exactly where a human review or a
stateless bot would wave it through. It is **one** documented catch, presented as such — not a market
validation.

**Synthetic mechanism benchmarks (medium-high).**
- Large controlled-mutation suite (240 known-truth pairs): precision 0.93 / recall 0.93, an **11.6×
  reduction in false alarms** vs a naive path-scope watcher (58 → 5). Synthetic fixtures, known
  labels. ([`BENCHMARK_CURRENT.md`](BENCHMARK_CURRENT.md), protocol pre-registered.)
- Binding-lifecycle suite (808 pairs): trigger recall **0.54 → 1.00** once the symbol-index binding
  is enabled, with alarm precision **1.00** (zero false `BROKEN`). The gutted-body ceiling is shown,
  not hidden — an existence checker re-triggers but cannot see a behavior change; only a C4 test can.
  ([`BENCHMARK_BINDING_LIFECYCLE.md`](BENCHMARK_BINDING_LIFECYCLE.md).)

**Public-repo reproducibility (scoped).**
[`BENCHMARK_PUBLIC_REAL_REPOS.md`](BENCHMARK_PUBLIC_REAL_REPOS.md) shows byte-identical results on
frozen SHAs of public repos (e.g. `humanize`, `python-dotenv`) — evidence the mechanism reproduces on
real code, **not** a claim of broad real-world coverage.

**First-hand lifecycle (this audit).** The full new-user path — seal → drift → `REVOKED` (exit 4),
plus the `--strength-gate` `off/warn/fail` ladder with atomic no-write on refusal — was run end-to-end
in a throwaway repo and matched the documented behavior exactly. (See
[`PRODUCTION_READINESS_AUDIT.md`](PRODUCTION_READINESS_AUDIT.md) §5.)

**Limitations of the evidence.** The benchmarks are mostly synthetic; the real-catch ledger is short
(quality over quantity is the explicit stance); coverage is Python-centric. None of this is offered
as "validated in production at scale," and the docs are careful never to say so.

## The trigger-vs-truth ceiling

This is the single most important idea for using Dorian honestly, and the project refuses to blur it
into one number:

- **Trigger axis (binding):** *when* is a claim re-checked? A claim is well-bound if every file whose
  change could falsify it is in the claim's watch set. `--binding-gate` audits this. A weak binding is
  a **coverage/confidence** gap (the claim might be skipped), **never** proof the claim is false.
- **Truth axis (strength):** *can the checker actually falsify the claim's kind?* A `behavior` claim
  backed only by a `symbol:` existence check is perfectly triggerable yet cannot detect a behavior
  change. `--strength-gate` audits this and (in `fail` mode) refuses to seal a load-bearing claim whose
  checker is too weak for its kind.

A claim is only as strong as **both** axes. Dorian's design keeps them separate, reports both, and —
crucially — never lets a weak binding or weak strength masquerade as "the claim is false." Weak ≠
false; it means *low confidence, go strengthen the checker.* This honesty about its own ceiling is
itself part of why the tool is trustworthy as a gate.

## Example user journey

Verified this session (commands are real; install is the published package):

```bash
# 1. install — core has zero runtime dependencies
pip install dorian-vwp

# 2. initialize a born-verifiable starter (claims.json, a change note, a GitHub Action)
dorian init

# 3. make a claim (here, by hand) that a function exists where a note says it does
cat > claims.json <<'JSON'
{"claims": [
  {"id": "handler-exists", "text": "handler() lives in app.py.",
   "kind": "reference", "load_bearing": true,
   "checkers": [{"type": "C3", "program": "symbol:app.py::handler"}]}
]}
JSON

# 4. verify — seals a warrant only if the claim is true right now (born-verifiable)
dorian verify note.md --claims claims.json        # -> verified 1/1 claim(s)   (exit 0)
dorian status                                     # -> WARRANTED note.md

# 5. change the code so the claim stops being true (rename the function)
#    note.md never changes; git and CI stay quiet

# 6. revalidate — re-checks only the intersecting claims
dorian revalidate --since HEAD~1                  # -> handler-exists BROKEN; WARRANTED -> REVOKED  (exit 4)
dorian status                                     # -> REVOKED note.md  BROKEN=1

# optional, opt-in: catch *under-verified* load-bearing claims before they seal
dorian verify note.md --claims claims.json --strength-gate=fail
#   refuses (exit 4, no sidecar) if e.g. a `behavior` claim is backed only by an existence check
```

Trust states map to exit codes: `0` trusted/warranted, `3` degraded (a non-load-bearing claim broke),
`4` revoked or seal-refused, `5` errored (a checker could not run — never a silent pass), `6` scope.
The GitHub Action's default `fail_on: revoked` turns a broken load-bearing promise into a blocked PR.

## Adoption fit

**Best fit:**
- Teams using AI coding agents who want the agent's *claims*, not just its code, held to account.
- Maintainers who want PR claims to remain true across later commits — durable, self-rechecking.
- Trusted internal repositories (the security model assumes you trust claim authors).
- Python-heavy, pytest-using projects (C4 behavior claims are strongest there).
- Teams that want **local, deterministic, auditable** evidence they can use as a CI gate.

**Poor fit:**
- Running untrusted public-fork checkers without external sandboxing (Dorian is not a sandbox; use
  `--checker-source base`/`--deny-exec` and a real sandbox, or don't).
- Teams wanting a hosted SaaS dashboard or analytics.
- Teams expecting LLM-style semantic judgment at check time (by design, there is none).
- Languages/claim shapes outside the current checker grammar (the deterministic checkers are
  Python-/data-centric).

## Bottom line

Most tooling tries to make AI write better claims. Dorian does something more durable: it makes claims
**checkable, sealed, and self-rechecking**, then gets out of the way — no tokens, no dashboard, no
opinion, just a deterministic verdict that stays correct as the code moves underneath it. Its evidence
is honest and modest about its ceiling, and it holds its own README, release process, and benchmarks
to the same standard it asks of you. For a trusted repo where agents make promises about code, that is
a genuinely useful — and unusually honest — thing to have.
