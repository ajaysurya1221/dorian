# Command reference

Every `dorian` subcommand, the flags that matter, and the exit-code contract. The authoritative
surface is the parser in `src/dorian/cli.py` (`dorian --help`); this page is the annotated tour.
The narrative of how the pieces fit is in [`OVERVIEW.md`](OVERVIEW.md).

## Command surface

The core loop is `verify` (auto-capture the read-set, run every checker, seal the `.warrant`) →
`revalidate` (re-check only what changed). `capture` + `seal` are the lower-level path for C1 span
claims.

- `dorian init [--force] [--dry-run]` — first-run scaffolding: writes a born-verifiable starter
  `claims.json`, the change note it backs, and a `.github/workflows/dorian.yml` Action workflow.
  Writes files only (never runs a checker or executes code), stays inside the repo, and skips
  existing files unless `--force`. The global `--json` prints a machine-readable plan.
- `dorian claude-code install-claim-warrants [--with-hook] [--dry-run] [--force]` — scaffold a
  project-local Claude Code skill (`/dorian-claim-warrants`) that drafts a change note + `claims.json`
  for the checkable facts your agent claimed, plus review-first settings examples and an opt-in,
  reminder-only Stop hook. The model only drafts; `dorian verify` proves. Writes files only; idempotent.
  See [`docs/DORIAN_CLAIM_WARRANTS_CLAUDE_CODE_SKILL.md`](DORIAN_CLAIM_WARRANTS_CLAUDE_CODE_SKILL.md).
- `dorian verify <artifact> --claims claims.json` — the one-shot agent-claims entry point:
  auto-derive the read-set from each C3/C4/C5 checker, then seal (born-verifiable). C1 span claims
  use `dorian capture` + `dorian seal` instead.
- `dorian verify … --binding-gate off|warn|fail` (also on `seal`; default `off`) — an opt-in
  weak-binding review gate: `warn` prints binding diagnostics after a successful seal; `fail`
  refuses the seal (writing nothing, exit 4) when a claim carries a high-risk weak-binding flag.
  It never marks a claim false and never changes trust state; `single-file` is warn-only.
- `dorian verify … --strength-gate off|warn|fail` (also on `seal`; default `off`) — the **truth-axis**
  companion to `--binding-gate`. Binding gates *when* a claim re-checks; strength gates *whether* its
  checker can falsify it. `warn` prints checker-strength/adequacy diagnostics after a successful seal;
  `fail` refuses the seal (writing nothing, exit 4) when a **load-bearing** claim's checker is too weak
  to falsify its kind — a `behavior` claim backed only by an existence/text/opaque-shell checker, a
  `quantity` claim backed only by existence, or an unbacked claim. It never marks a claim false and
  never changes trust state; non-load-bearing claims and merely-`medium` risk never block.
  - The two gates are **orthogonal and compose**, one per layer of the protocol (see
    [Binding is a re-check trigger, not a behavior proof](BINDING.md#binding-is-a-re-check-trigger-not-a-behavior-proof)
    and [`docs/VALIDATION_HONESTY.md`](VALIDATION_HONESTY.md)): `--binding-gate` is the
    **trigger/selection** axis (*will a relevant later change re-check this claim?*); `--strength-gate`
    is the **truth/alarm** axis (*can the checker actually falsify this claim?*). A claim can be
    perfectly bound yet weakly backed, or strongly backed yet weakly bound — turn on whichever axis
    your review cares about, or both. Neither ever marks a claim false; both map to seal-refused (exit 4).
    Copy-paste walkthrough: [`docs/STRENGTH_GATE_DEMO.md`](STRENGTH_GATE_DEMO.md).
- `dorian blast <path|warrant-id> [--max-depth N]` — downstream warrants reachable through the
  derives graph. When `revalidate` newly breaks a claim, every downstream warrant gets a `recalled`
  event: a flag only — downstream is never re-checked and its states are untouched. Re-seal with
  `seal --supersede <old-id>` so downstream warrants sealed against the old id stay reachable.
- `dorian bindings <artifact>` — binding-quality diagnostics (unbacked, single-file, short-literal,
  ambiguous-mention, trigger-only-symbol, unwatched-mention) **plus per-claim checker-strength and
  claim-risk** (it classifies each checker's *truth strength* and flags adequacy mismatches — a
  `behavior` claim backed only by an existence checker, a vacuous pytest node). Informational, never a
  gate; output carries file paths only, never matched content.
- `dorian bind-suggest --claims claims.json` — read-only preview of the files `verify` would auto-bind
  for each claim, **with provenance** (symbol-definer, config-key, and C4 test-import dependency), the
  ambiguous symbols/keys it would skip, and any unparseable config file. Writes nothing, never a gate.
- `dorian revalidate --checker-source base` (also Action `checker_trust: base`; default `head`) —
  resolve each claim's checker spec from the `--since` base ref so a PR-added or PR-modified executable
  checker is never executed (public/fork PRs). Fail-closed, **not a sandbox** — pair with `--deny-exec`.
- `dorian rebind <artifact>` — re-derive a warrant's symbol-definer **and C4 test-import** watches with
  the current binding logic and re-seal it (born-verifiable, superseding the old id), so a warrant sealed
  before the symbol index or C4 import binding existed gains the wider watches. The watch only ever
  widens; a claim that has since become false refuses the re-seal (exit 4) rather than being laundered
  into a fresh trusted state.
- `dorian suggest-data-checks <path> [--columns ...] [--out f]` — born-verifiable C5 checker
  suggestions from a data file's current state, for review and pasting into a claim's `checkers` list.
- `dorian suggest-claims <path.py> [--out f]` — born-verifiable C3 claim suggestions (`symbol:` for
  defs/classes, `py-const:` for literal constants) for a Python file: each candidate is run and only
  passing ones are emitted, `load_bearing` defaults to false, ambiguous symbols are skipped. Review
  scaffolding (existence/value, not behavior) — see
  [`docs/design/SUGGEST_CLAIMS.md`](design/SUGGEST_CLAIMS.md).
- `dorian export --in-toto <artifact>` — project a sealed `.warrant` into an experimental in-toto
  `ClaimVerification` Statement (deterministic, no signing, zero deps); experimental interop —
  see [`docs/ATTESTATION_INTEROP.md`](ATTESTATION_INTEROP.md).
- `dorian report --audit` — the full event log as `dorian-audit-v1` JSONL, byte-identical across
  runs; checker details truncated to 160 chars to bound source-content carryover.
- `dorian revalidate --format md|json` — `md` is the PR-comment body posted by the
  [GitHub Action](../action/) (`action/action.yml`, composite, no third-party actions).
- `dorian verify … --deny-exec` (also on `seal`/`revalidate`; env `DORIAN_DENY_EXEC=1`) — refuse to
  *run* the executable checker families (C4 pytest, C5 shell): they ERROR instead of executing, so a
  blocked claim never seals and never silently passes revalidate. `--deny-shell` is the narrower form
  (blocks C5 shell, still allows C4). For untrusted/fork contexts; fail-closed, not a sandbox.
- `dorian seal --no-quotes` — content-free sidecars: anchor line numbers stay, quotes are dropped
  (the warrant id changes accordingly).
- Seal-time scope lint: `[tool.dorian.scopes] restricted = [globs]` in the *target* repo's
  pyproject.toml refuses to seal read-sets touching restricted paths (exit 6); `--allow-restricted`
  overrides and is receipted in the sealed event. (It restricts the auto-captured read-set — the files
  a claim's checkers name, plus the file `verify` binds from a symbol the claim mentions — not what an
  executed checker may read or write; it is not a sandbox.)
- `dorian bench large-mutation` — the v0.7.0 controlled-mutation benchmark (numbers-only aggregate +
  stratified summary; [`docs/BENCHMARK_v0.7.0.md`](BENCHMARK_v0.7.0.md)). `dorian bench mutation`
  is the earlier, smaller benchmark; `dorian bench churn` measures extraction stability.
- `dorian bench binding-lifecycle` (`--quick` for a CI subset) — the two-layer trigger-vs-truth
  benchmark for symbol binding ([`docs/BENCHMARK_BINDING_LIFECYCLE.md`](BENCHMARK_BINDING_LIFECYCLE.md)).
  `dorian bench realworld-usecases` runs the offline public-case reproductions
  ([`docs/REALWORLD_USECASES.md`](REALWORLD_USECASES.md)).
- `dorian bench warrant-quality <artifact>` — offline per-claim mutation scoring: for each claim, does
  its checker catch the drift it implies (caught / missed / brittle / ceiling)? Deterministic, never
  mutates the real repo. Separates trigger from verdict; see [`docs/V1_SCOPE.md`](V1_SCOPE.md).

Exit codes: `0` ok/TRUSTED · `2` usage/infra (incl. a C1 or C5 `shell:` claim handed to `verify`) ·
`3` DEGRADED · `4` REVOKED/integrity · `5` ERRORED-only (checkers could not run — never conflated with
broken) · `6` scope violation.

## Claim extraction is frozen

`--extract` drafts claims with an LLM from a blank file. It still works but is **frozen and
experimental** — it failed its stability gate twice, and the supported, recommended path is now an
agent (or you) emitting `claims.json` directly and running `dorian verify`. See
[`docs/AGENT_CLAIMS.md`](AGENT_CLAIMS.md); treat any extracted claims as drafts for review, never
stable warrant inputs.
