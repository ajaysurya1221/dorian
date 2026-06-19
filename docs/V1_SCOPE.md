# What V1 means — and what it does not

dorian's V1 strengthening is **deterministic strengthening on supported domains**, not a
promise of universal correctness. This page states the boundary so no feature or
benchmark can be read as more than it is. It is the companion to
[`VALIDATION_HONESTY.md`](VALIDATION_HONESTY.md) (evidence wording) and
[`SECURITY_BOUNDARY.md`](SECURITY_BOUNDARY.md) (execution/trust).

## What V1 adds

All additive and backward-compatible; default behavior is unchanged unless you opt in.

- **Python structural checkers** — `py-signature:` and `py-const:` (C3 subgrammars) compare
  parsed AST structure and literal **values**, closing the `symbol:` existence ceiling and the
  `string:`/`regex:` comment-survival false-pass for Python signatures and constants.
- **Semantic-context search** — `code:` runs a regex over comment/docstring-stripped Python,
  so a fact surviving only in a comment or docstring FAILs while the same fact in real code
  passes. (`spec/checkers.md`.)
- **Checker-strength / claim-risk diagnostics** — `dorian bindings` and the `--binding-gate`
  warn output now classify each checker's *truth strength* and flag kind-vs-strength
  adequacy mismatches (a `behavior` claim backed only by an existence checker; a vacuous
  pytest node). Advisory; it never changes a verdict, trust state, or exit code.
- **Multi-index binding** — config keys in tracked `.toml`/`.json` files now widen a claim's
  re-check trigger set (with provenance in `bind-suggest`). Conservative and trigger-only.
- **C4 import-aware binding** — a `pytest:` test's statically resolved repo-local imports
  (stdlib `ast`, read-only — no execution) now widen the behavior claim's re-check trigger set,
  so an implementation edit re-runs the test even when the claim text names no symbol. Trigger
  coverage only — the test still decides truth (`dorian bench c4-import-binding`).
- **Trusted-base checker-source mode** — `revalidate --checker-source base` / Action
  `checker_trust: base` runs only base-approved checker specs, for public/fork PRs.
- **Warrant-quality harness** — `dorian bench warrant-quality` scores per-claim whether a
  checker catches the drift it implies, offline and deterministically.

## What V1 does NOT mean

- **Not universal semantic correctness.** dorian verifies *stated claims against the source*
  with deterministic checkers. It cannot prove arbitrary prose, runtime behavior without a
  test, external-system state, or anything outside a supported checker/binding domain.
- **The trigger-vs-truth ceiling is real and visible, not removed.** Binding decides WHEN a
  claim is re-checked; the checker decides WHETHER it is false. A `symbol:`/`py-signature:`
  checker is blind to a body-only ("gutted body") change — only a `pytest:` test catches that.
  The checker-strength diagnostics and the warrant-quality harness *surface* this; they do not
  eliminate it.
- **No public-fork safety beyond the trust root.** `checker_trust: base` stops PR-authored
  executable checkers from running, but a base-approved `pytest:` checker can still execute
  PR-head code. It is a checker-source trust root, **not a sandbox**; for untrusted forks
  combine it with `deny_exec: true` (or external isolation). `--deny-exec`/`--deny-shell` are
  fail-closed, not sandboxes.
- **Config binding is TOML/JSON only.** YAML is not indexed — parsing it needs a third-party
  dependency and dorian's core has zero runtime deps. An unparseable supported config file is
  surfaced as a diagnostic, never silently skipped, but a key dorian cannot index is an honest
  miss, not a guarantee.
- **`code:`/structural forms are Python-only.** Other languages still rely on raw `string:`/
  `regex:` text search, which retains the comment/docstring survival class.
- **The LLM extractor stays draft/experimental.** V1 does not promote `--extract`; emit claims
  directly (`docs/AGENT_CLAIMS.md`).
- **Benchmarks prove reproducibility on named inputs**, never "works on real repos" — see
  `VALIDATION_HONESTY.md`. Historical result docs (v0.7.0, 0.9.0) are labeled historical;
  current-version numbers live in `BENCHMARK_CURRENT.md`.

## Known limitations carried into V1 (documented, not fixed)

- **Audit/state atomicity** — a claim/trust-state change and its audit event commit in
  separate transactions; a crash between the two can leave the event missing (`fold.py`).
- **Ambiguous bindings are skipped, not resolved** — a symbol or config key defined in more
  than one file is left unwatched and surfaced for manual binding, never guessed.
- **ERROR is never BROKEN** — a checker that cannot run (bad program, missing engine, blocked
  by policy, unresolved base sidecar) is ERRORED, never a staleness verdict, end to end.
