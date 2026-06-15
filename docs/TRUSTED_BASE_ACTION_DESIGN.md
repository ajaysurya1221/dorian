# Trusted-base Action mode — design + status

> **STATUS: IMPLEMENTED (V1).** `dorian revalidate --checker-source {head,base}` and the Action
> `checker_trust: head|base` input now implement this design. Default is `head` (today's behavior,
> unchanged). The §6 test matrix is implemented in `tests/test_trusted_base.py` (PR-added/modified
> executable checkers never execute — proven with a sentinel side effect; missing/tampered base
> sidecar fails closed; a rewritten checker is surfaced as a trust-root change; deny-exec composes).
> The non-sandbox caveat in §2/§7 still holds and is stated in user docs: a base-approved
> `pytest:`/`shell:` checker can still execute PR-head code, so `base` mode is a *checker-source trust
> root*, not a sandbox.

## 1. Problem

The composite Action ([`action/action.yml`](../action/action.yml)) runs `dorian revalidate`, which
executes the checker programs found in the **checked-out** `.warrant` sidecars. C3 and typed C5 only
read files, but **C4 (`pytest:`) and C5 `shell:` execute code**. On a pull request from a fork, the
PR branch controls those sidecars — so an attacker could add or edit a `.warrant` whose C4/C5 checker
runs arbitrary code on the runner. That is why the Action is documented as **trusted/internal repos
only** today (see the Action's
[security notes](../action/README.md#security-checker-execution-and-untrusted-pull-requests)).

Trusted-base mode is a *narrowing* that prevents execution of PR-authored or PR-modified executable
checker specs while preserving today's behavior for trusted repos. It does **not** sandbox PR-head
code.

## 2. Principle

**Only execute checker specs that already exist, unchanged, on the base branch.** The base branch is
maintainer-reviewed; the PR branch is not. Concretely, for each affected claim:

- Resolve the claim's checker spec from the **base** sidecar (the version at `--since`'s ref).
- Execute it against the **PR head** sources (so a real drift in the PR is still caught).
- If the PR branch **adds** a sidecar/claim, or **changes** an existing claim's executable checker
  (C4/C5 `shell:`) relative to base, **do not execute it** — mark it `skipped (unreviewed checker)`
  and surface it in the PR comment. Non-executable checkers (C3, typed C5) introduced by the PR may
  still run, since they only read files (subject to scope lint).

This means a forked PR can never get a new or altered code-executing checker to run; it can only be
held to the checks a maintainer already approved on base. It does not make arbitrary PR-head code
safe: a base-approved C4 `pytest:` checker may still import or execute PR-head code.

## 3. Mode selection (default preserves today's behavior)

A new Action input `checker_trust: base | head` (or a `dorian revalidate --checker-source base` flag):

- `head` (**default**) — today's behavior exactly: execute the checked-out (PR) sidecars. Correct and
  unchanged for trusted/internal repos. Documented as unsafe for untrusted forked PRs.
- `base` — trusted-base mode above. The only mode a public repo accepting forked PRs should use.

Default `head` guarantees **zero behavior change** for every existing user unless they opt in.

## 4. Hard constraints (must not be weakened)

- **Never use `pull_request_target`** and never mount secrets into a job that runs PR-controlled code.
  The trigger stays `pull_request`; `GITHUB_TOKEN` keeps `contents: read`, `pull-requests: write`.
- The PR-controlled checker output stays fenced with `::stop-commands::` exactly as today.
- Trusted-base mode must **fail closed**: if base resolution is ambiguous or a base sidecar can't be
  read, skip (don't execute the PR version) and report it — never fall back to executing PR checkers.
- No change to `TrustState`/`ClaimState`/fold policy or the sidecar schema. This is purely *which
  checker spec is selected for execution*, computed before any checker runs.

## 5. Where it lives

- A `revalidate` option that, given `--since <base>`, reads each affected claim's checker spec from
  the base ref (via `gitio`) instead of the working tree, and classifies PR-introduced executable
  checkers as `skipped`. The diff/selection logic already resolves base content for `--since`.
- The Action gains the `checker_trust` input, defaulting to `head`, threaded through env (never inline
  `${{ }}` into the script, per the existing pattern).
- `action/README.md` gains a prominent trusted-base section; the README CI snippet stays `head` for
  trusted repos and documents `checker_trust: base` for public/forked-PR repos.

## 6. Test matrix (write before any implementation)

1. **Default unchanged** — `checker_trust` unset ⇒ identical output/exit to today on a fixture PR.
2. **Base-unchanged checker runs** — a claim whose checker is identical on base and head executes and
   can fold BROKEN on a real PR drift.
3. **PR-added executable checker is skipped** — a PR that adds a `.warrant` with a C4/C5 `shell:`
   checker ⇒ that checker is `skipped (unreviewed)`, never executed; surfaced in the md output.
4. **PR-modified executable checker is skipped** — base has `pytest:a`, PR changes it to `shell:rm…`
   ⇒ skipped, not executed.
5. **PR-added non-executable checker may run** — a PR adding a C3 `symbol:`/`path:` checker runs
   (read-only), subject to scope lint.
6. **Fail-closed** — unreadable/ambiguous base sidecar ⇒ skip + report, never execute the PR version.
7. **No secret exposure** — assert the workflow never uses `pull_request_target` and mounts no secrets.

## 7. Out of scope

Trusted-base mode does not sandbox PR-head code, and there is no sandboxing of executed checkers
(still "trusted repos for `head` mode"); no auto-merge; no change to comment posting beyond surfacing
skipped checkers. If full implementation proves broader than this, ship only the
`revalidate --checker-source` selection + tests first, and the Action input second.
