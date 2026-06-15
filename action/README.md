# dorian GitHub Action

Composite action that re-checks warranted claims touched by a pull request
(`dorian revalidate --since <base>`), posts the result as a **sticky PR
comment**, and gates the check on the revalidation verdict.

No third-party actions are used: the steps are plain `bash` and the comment is
managed with the `gh` CLI (preinstalled on GitHub-hosted runners).

## Usage

```yaml
name: dorian
on: [pull_request]

permissions:
  contents: read
  pull-requests: write   # sticky comment (update-or-create)

jobs:
  revalidate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0   # REQUIRED: revalidate diffs against the PR base
                           # sha, which a shallow clone does not contain
      - uses: ajaysurya1221/dorian/action@main
        with:
          fail_on: revoked
          # until the first PyPI release, install from source:
          install: 'dorian-vwp @ git+https://github.com/ajaysurya1221/dorian.git'
```

`fetch-depth: 0` is required because `dorian revalidate --since` runs
`git diff` against the pull request's base sha; the default shallow checkout
(depth 1) does not have that commit, so the diff — and therefore the whole
run — would fail as a usage error.

## Security: checker execution and untrusted pull requests

> A `.warrant` file can reference executable checker logic. Do not execute
> checker specs from untrusted pull requests. For public repositories, use
> trusted-base checker definitions and disable shell/custom executable
> checkers until reviewed.

**What the Action actually runs.** `dorian revalidate` executes the checkers
of every affected claim *as found in the checkout* — and under `pull_request`
the checkout is the PR's merged tree, including any `.warrant` files the PR
added or changed. C4 checkers run `pytest`; C5 `shell:` checkers run shell
commands. So a PR that edits a sidecar can cause this Action to execute
PR-authored commands.

**Is that safe for public forked PRs?** It is the *same* exposure as any CI
workflow that runs a PR's test suite — under a plain `pull_request` event,
fork PRs get no secrets and a read-only `GITHUB_TOKEN` — but with two real
caveats:

1. A `.warrant` file is a **non-obvious executable input**. Reviewers who
   would scrutinize a workflow or `conftest.py` change may wave through a
   "docs-only" diff that swaps a checker `program`.
2. In the default `head` mode the verdict is **self-attested by the PR tree** — a
   PR can rewrite a sidecar so a broken claim re-verifies. **`checker_trust: base`
   fixes exactly this** (see below): it sources every checker spec from the base
   ref, so a PR rewriting a spec can no longer weaken the verdict. Use `head` only
   for trusted/internal repos.

**deny-exec input.** Set `deny_exec: true` (or `deny_shell: true`) on the Action to
refuse the executable checker families during revalidation: C4 pytest and C5 shell
ERROR instead of executing, so a PR-authored sidecar cannot make this Action run its
code. It flows through the `DORIAN_DENY_EXEC` env fallback; the default `false`
preserves today's behavior for trusted/internal repos. This is fail-closed but **not
a sandbox**: on its own it removes code execution but does not address the
self-attested-verdict problem for *non-executable* checkers — that is what
`checker_trust: base` adds, and the two compose (use both for untrusted forks). See
`SECURITY.md` and `docs/SECURITY_BOUNDARY.md`.

```yaml
# untrusted / public-fork posture
- uses: ajaysurya1221/dorian/action@main
  with:
    deny_exec: "true"   # C4/C5 ERROR instead of executing
```

**trusted-base mode (`checker_trust: base`).** This is the trust-root fix for the
self-attested-verdict problem. With `checker_trust: base`, the Action resolves each
claim's checker SPEC from the **base ref** and runs it against the PR-head sources, so
a PR-added or PR-modified executable checker is never executed and a rewritten checker
cannot self-attest a verdict — the base-approved spec wins, and the change is surfaced
in the PR comment. A missing or tampered base sidecar **fails closed** (ERRORED, never
executed). Implemented and proven by the
[trusted-base test matrix](../docs/TRUSTED_BASE_ACTION_DESIGN.md).

```yaml
# public / forked-PR posture: trusted checker specs + no code execution
- uses: ajaysurya1221/dorian/action@main
  with:
    checker_trust: base   # run only base-approved checker specs
    deny_exec: "true"     # and refuse to execute even those (belt and braces)
```

**It is a checker-source trust root, not a sandbox.** A base-approved `pytest:` checker
can still import and execute PR-head code, so for fully untrusted forks combine
`checker_trust: base` **with** `deny_exec: true` (or external isolation). Default
`checker_trust: head` is unchanged and correct for trusted/internal repositories, where
everyone who can open a PR is already trusted to run code in CI. For public repositories,
treat any PR that touches a `.warrant` file as a code change requiring the same review as
a CI change.

Hard rules either way:

- Trigger on `pull_request`, **never** `pull_request_target` (a privileged
  context plus a PR-controlled tree is exactly the combination that turns
  the exposure above into secret exfiltration).
- Do not mount secrets into jobs that run this Action on untrusted PRs.
- On fork PRs the default `GITHUB_TOKEN` is read-only, so the sticky-comment
  step cannot post and fails loudly — one more reason this Action currently
  targets trusted/internal repositories.
- Infrastructure failures stay loud: exits 2 (usage) and 5 (checkers could
  not run) fail the step regardless of `fail_on` (except the explicit
  `never` escape hatch) and are never reported as stale or broken claims.

## Inputs

| input           | default                                      | meaning                                                                  |
| --------------- | -------------------------------------------- | ------------------------------------------------------------------------ |
| `fail_on`       | `revoked`                                    | when to fail the step: `revoked` (exit 4 only), `degraded` (3 or 4), `never` |
| `base`          | `${{ github.event.pull_request.base.sha }}`  | git ref passed to `dorian revalidate --since`                            |
| `install`       | `dorian-vwp`                                 | pip spec; pin `dorian-vwp==0.6.*`, or `.` for checkout installs          |
| `deny_exec`     | `false`                                      | refuse to run executable checkers (C4 pytest, C5 shell): they ERROR. For untrusted/fork PRs; fail-closed, not a sandbox |
| `deny_shell`    | `false`                                      | narrower than `deny_exec`: block only C5 shell, still allow C4 pytest    |
| `checker_trust` | `head`                                       | `head` runs the checked-out checker spec (trusted repos); `base` runs the base-ref spec so PR-authored executable checkers never run (public/fork PRs) |

Until the first PyPI release of `dorian-vwp`, set `install` to a source spec:
`install: 'dorian-vwp @ git+https://github.com/ajaysurya1221/dorian.git'`.

## Behavior

- **Stateless CI.** Every run starts from the sidecars in the checkout:
  `dorian sync` rebuilds the local index, then `dorian revalidate` re-checks
  only the claims bound to changed paths. Nothing is persisted between runs.
- **Silence on zero-affected.** When no warranted claim is touched (and
  nothing is recalled), the markdown body is the no-op sentinel
  (`dorian: no warranted claims affected.`) and the comment step is skipped
  entirely — quiet PRs stay quiet, and no empty comments are posted.
- **Sticky comment.** Otherwise the action looks for an existing PR comment
  containing the `<!-- dorian -->` marker: if found it is updated (PATCH),
  else a new one is created (POST). One comment per PR, never duplicates.
- **Verdict gating.** The real `dorian revalidate` exit code is captured and
  mapped by `fail_on`:
  - `revoked` (default): fail iff exit code is 4 (a touched warrant REVOKED);
  - `degraded`: fail iff exit code is 3 or 4 (DEGRADED or REVOKED);
  - `never`: always succeed (report-only mode).
- **Usage/infra failures fail loudly.** Exit 2 (usage: bad ref, shallow
  clone, missing repo) and exit 5 (ERRORED-only: checkers could not run) are
  *not* verdicts — ERROR is never FAIL — so they fail the step with a
  distinct message **regardless of `fail_on`**, except under `fail_on: never`.
  Rationale: a checker that cannot run must surface as a visible infra
  failure, not silently pass a gate; but `never` is an explicit report-only
  escape hatch, and overriding it would make report-only mode impossible.
