# Security and safe runners

One opinionated, copy-paste recipe for running dorian's GitHub Action on
**public / untrusted fork PRs**, plus the reasoning behind each setting. For the
full trust model — which checkers execute code, what the env strip does, what
scope-lint does and does not contain — read
[docs/SECURITY_BOUNDARY.md](SECURITY_BOUNDARY.md). This page is the runner recipe;
that page is the boundary.

## The one safe recipe (public / untrusted fork PRs)

Drop this into a workflow file (for example `.github/workflows/dorian.yml`):

```yaml
on: pull_request          # never pull_request_target for untrusted forks
permissions:
  contents: read
  pull-requests: write

jobs:
  dorian:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # the action needs full history to revalidate --since base
      - uses: ajaysurya1221/dorian/action@v1.3.0
        with:
          checker_trust: base   # resolve checker SPECs from the trusted base ref
          deny_exec: "true"     # C4 pytest / C5 shell ERROR instead of executing
          fail_on: never        # start report-only; tighten once you trust the signal
```

Three settings carry the safety. The rest of this page explains why each one is
load-bearing and, just as importantly, what it does **not** buy you.

## This is policy, not a sandbox

`checker_trust: base` is a trust-**root** control, not execution isolation. With
`checker_trust: base` the action reads each claim's checker SPEC from the **base
ref** (the branch the PR targets) and runs it against the PR-head sources. So a
fork PR cannot introduce a *new* executing checker, and it cannot rewrite an
existing checker to self-attest a passing verdict — the base-approved spec wins,
and the change is surfaced in the PR comment. A missing or tampered base sidecar
fails closed (ERRORED, never executed).

What it is **not**: it does not isolate execution. A `pytest:` checker that was
already approved in the base ref still runs `python -m pytest` against the
**PR-head** test and source files, so it can import and execute code the fork
author wrote. `checker_trust: base` decides *which checker specs are allowed to
run*; it does nothing about *what those allowed checkers then do*. That is why
the recipe also sets `deny_exec: "true"`. Never describe `checker_trust: base` as
a sandbox — it is a checker-source trust root.

## Why `deny_exec: "true"` matters on untrusted forks

`deny_exec: "true"` removes the ability to execute code at all. It fail-closes the
two checker families that spawn a process:

- **C4 `pytest:<nodeid>`** — would run `python -m pytest`.
- **C5 `shell:<command>`** — would run an arbitrary command.

Under deny-exec, a blocked checker becomes **ERROR — never PASS and never FAIL**.
A checker that was refused permission to run has not proven the claim true and has
not proven it false, and the surrounding protocol already fails closed on ERROR
(seal refuses to be born; revalidate folds ERROR to ERRORED, never to a silent
pass). So a fork PR that tries to smuggle an executing checker cannot make this
action run its code, and cannot make a load-bearing claim silently pass either.

The pairing matters: `checker_trust: base` stops a fork from *introducing* a new
executing checker; `deny_exec: "true"` stops even a *base-approved* executing
checker from running PR-head code. For untrusted forks, use both.

**One honest caveat.** deny-exec gates only the process-spawning families (C4
pytest, C5 shell). The **typed C5 data reads** — `rowcount`, `schema`,
`nullrate`, `domain`, `freshness`, `snapshot`, `reconcile` — read CSV / SQLite /
parquet **in-process**; they are deliberately not deny-exec-gated because they do
not spawn a command. They are bounded instead: SQLite reconcile queries run under
a read-only authorizer and a per-query wall-clock timeout (5s) that interrupts a
pathological query (for example an infinite recursive CTE) and reports ERROR. So
deny-exec is about *code execution*, and the typed data path has its own bounded
in-process protection rather than relying on deny-exec.

## Why never `pull_request_target` for untrusted forks

`pull_request_target` runs the workflow in the **base** repository's context — with
a read/write `GITHUB_TOKEN` and access to repository secrets — while checking out
a tree the fork author controls. That combination (write-capable secrets plus an
attacker-controlled tree) is exactly what turns any of the exposure above into
secret exfiltration. Always trigger on `pull_request`, where fork PRs get a
read-only token and no secrets. Never use `pull_request_target` for untrusted
forks. (On fork `pull_request` runs the default token is read-only, so the sticky
PR-comment step needs `pull-requests: write` in `permissions` — that is the write
scope in the recipe above, and it is scoped to PR comments, not to code or
secrets.)

## Trusted / internal repos

If everyone who can open a PR is already trusted to run code in your CI — your own
repo, an internal repo, a team you trust — you can run the executing checkers
(C4 pytest, C5 shell) and get the full signal. Use the defaults:

```yaml
on: pull_request
permissions:
  contents: read
  pull-requests: write

jobs:
  dorian:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: ajaysurya1221/dorian/action@v1.3.0
        # checker_trust defaults to head, deny_exec defaults to false:
        # executing checkers run, because contributors are trusted.
        with:
          fail_on: revoked   # fail the check when a warranted claim is revoked
```

Here `checker_trust: head` (the default) runs the checked-out checker spec and
`deny_exec: false` (the default) lets C4/C5 execute — correct precisely because
the people who write the sidecars are trusted. Review a `.warrant` file the same
way you review code.

## Supply-chain note

dorian's own repository hardens its CI supply chain:

- Every third-party Action it uses is **pinned to a full commit SHA** (not a
  floating tag) across its workflows, so a re-tagged upstream action cannot
  silently change what runs.
- The `security` workflow runs **pip-audit** (SCA — audits the resolved
  dependency tree for known CVEs, including a weekly scheduled run to catch
  newly-disclosed advisories) and **bandit** (SAST — static analysis of
  first-party source). See [`.github/workflows/security.yml`](../.github/workflows/security.yml).

The action itself is composite and stdlib-only: it pulls in no third-party
actions, and installs only the `dorian-vwp` package you pin via the `install`
input.

---

See also [docs/SECURITY_BOUNDARY.md](SECURITY_BOUNDARY.md) for the full trust model.
