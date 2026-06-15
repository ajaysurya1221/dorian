# Security Policy

## Reporting a vulnerability

dorian is a solo, pre-1.0 project. To report a security issue, open a
[GitHub security advisory](https://github.com/ajaysurya1221/dorian/security/advisories/new)
(preferred) or a regular issue **without** exploit details and ask for a private
channel. Please do not post working exploits in public issues. There is no SLA;
expect a best-effort response.

## The one boundary you must understand

**dorian runs checker programs that are embedded in `.warrant` sidecars and in
`claims.json`. Two checker families execute code:**

- **C4** `pytest:<nodeid>` runs `python -m pytest` in a subprocess.
- **C5** `shell:<command>` runs an arbitrary command in a subprocess.

So a `.warrant` file or a `claims.json` is **executable input**. Running
`dorian verify`, `dorian seal`, or `dorian revalidate` on claims authored by
someone you do not trust is equivalent to running their code. The typed C5 data
forms (`rowcount`, `schema`, `nullrate`, `domain`, `freshness`, `snapshot`,
`reconcile`), C3 (`path`/`symbol`/`string`/`regex`), and C1 spans only read
files in-process and do not execute commands.

This is why dorian is built for **trusted, internal repositories**, and why the
GitHub Action is recommended for trusted/internal use only. See
[docs/SECURITY_BOUNDARY.md](docs/SECURITY_BOUNDARY.md) for the full FACT /
LIMITATION / SAFE-DEFAULT / UNSAFE breakdown.

## deny-exec: refuse to run executable checkers

When you cannot fully trust the claims (a fork PR, a sidecar a third party
edited, a CI job you do not want to grant code execution), pass `--deny-exec`:

```bash
dorian verify note.md --claims claims.json --deny-exec
dorian revalidate --since HEAD --deny-exec
```

Available on `seal`, `verify`, `revalidate`, and `rebind` (rebind re-runs every
checker to re-seal, so it is an executable surface too), with env fallbacks
`DORIAN_DENY_EXEC=1` and `DORIAN_DENY_SHELL=1` (`--deny-shell` blocks only C5
shell and still allows C4 pytest). Only the values `1`, `true`, `yes`, or `on`
(case-insensitive) deny; any other value, including a misspelling like `disable`,
leaves execution ENABLED — prefer the explicit `--deny-exec` flag. Under deny-exec
a blocked checker becomes `ERROR` — never PASS, never FAIL. A blocked load-bearing
claim therefore:

- **does not seal** (a warrant is born-verifiable; an ERROR at seal refuses), and
- **never silently passes** revalidate (a blocked recheck folds to ERRORED,
  exit 5, not VERIFIED and not BROKEN).

deny-exec is **fail-closed**: it removes the ability to run code, it does not
weaken any verdict.

## What deny-exec is NOT

deny-exec is **not a sandbox**. It decides *whether* the executable families run
at all; it does not constrain what an allowed checker may read or write, and it
does nothing about C4/C5 when you leave them enabled. There is no OS-level
isolation, no filesystem jail, no network policy. If you need those, run dorian
inside your own sandbox (container, restricted user, no secrets in env).

## Public fork PR CI

For public/forked-PR CI, use **trusted-base checker-source mode**:
`dorian revalidate --checker-source base` (Action input `checker_trust: base`). It
resolves each claim's checker SPEC from the trusted base ref and runs it against the
PR-head sources, so a PR-added or PR-modified executable checker is never executed and
a PR rewriting a checker spec cannot self-attest a verdict (the base-approved spec
wins). A missing or tampered base sidecar **fails closed** (ERRORED, never executed).
This is implemented and proven by the test matrix in
[docs/TRUSTED_BASE_ACTION_DESIGN.md](docs/TRUSTED_BASE_ACTION_DESIGN.md) §6
(`tests/test_trusted_base.py`).

It is a **checker-source trust root, not a sandbox**: a base-approved `pytest:` checker
can still import and execute PR-head code. So for fully untrusted forks, combine
`checker_trust: base` **with `deny_exec: true`** (or external isolation) — any executed
checker still runs with the runner's privileges. Do not wire dorian into
`pull_request_target` with a checkout of untrusted head.

## Supported versions

Only the latest release is supported. There are no backports.
